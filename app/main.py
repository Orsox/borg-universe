import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.repositories import (
    BorgRegistryRepository,
    ProjectRegistryBindingRepository,
    ProjectRepository,
    ProjectSpecRepository,
    TaskRepository,
)
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.projects import PROJECT_TYPES, ProjectCreate
from app.models.tasks import TaskCreate
from app.services.orchestration_settings_store import OrchestrationSettingsStore
from app.services.project_scanner import scan_drive_for_projects
from app.services.workflow_store import WorkflowStore
from app.ui import templates


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
    )
    app.include_router(api_router)

    def get_ui_context(client: SupabaseRestClient | None = None) -> dict[str, Any]:
        """Provides common UI context data like sidebar counts."""
        if client is None:
            try:
                client = SupabaseRestClient(settings)
            except SupabaseRestError as exc:
                logging.getLogger("borg_universe").error(f"UI Context: Failed to create client: {exc}")
                return {
                    "agent_count": 0, "skill_count": 0, "task_count": 0, "workflow_count": 0,
                    "system_status": "intervention", "supabase_configured": False, "mcp_configured": False,
                }
        
        try:
            agent_count = len(BorgRegistryRepository(client, "agents").list_items())
            skill_count = len(BorgRegistryRepository(client, "skills").list_items())
            task_count = len(TaskRepository(client).list_tasks())
            workflow_count = len(WorkflowStore(settings.workflows_root).list_workflows())
        except Exception as exc:
            logging.getLogger("borg_universe").error(f"UI Context: Failed to fetch counts: {exc}")
            agent_count = 0
            skill_count = 0
            task_count = 0
            workflow_count = 0
        
        return {
            "agent_count": agent_count,
            "skill_count": skill_count,
            "task_count": task_count,
            "workflow_count": workflow_count,
            "system_status": "configured" if settings.supabase_configured else "intervention",
            "supabase_configured": settings.supabase_configured,
            "mcp_configured": bool(settings.mcp_server_url),
        }

    # Export for other routers
    app.state.get_ui_context = get_ui_context

    @app.on_event("startup")
    async def startup_event() -> None:
        logger = logging.getLogger("borg_universe")
        if settings.supabase_configured:
            logger.info("Initializing Borg Universe: scanning agents and skills...")
            try:
                from app.api.borg import _repo
                from app.services.borg_scanner import scan_agents, scan_skills
                client = SupabaseRestClient(settings)
                
                # Perform scan
                agents = scan_agents(settings)
                skills = scan_skills(settings)
                
                agent_repo = _repo("agents", settings)
                skill_repo = _repo("skills", settings)
                
                # Sync with DB
                synced_agents = agent_repo.sync(agents)
                synced_skills = skill_repo.sync(skills)
                
                # Double check DB state
                db_agents = agent_repo.list_items()
                db_skills = skill_repo.list_items()
                
                logger.info(f"Borg Universe initialization complete.")
                logger.info(f"Agents - Found on disk: {len(agents)}, Synced: {len(synced_agents)}, DB Total: {len(db_agents)}")
                logger.info(f"Skills - Found on disk: {len(skills)}, Synced: {len(synced_skills)}, DB Total: {len(db_skills)}")
                
                if len(db_agents) == 0 and len(agents) > 0:
                    logger.error("CRITICAL: Agents found on disk but DB is empty after sync!")
                if len(db_skills) == 0 and len(skills) > 0:
                    logger.error("CRITICAL: Skills found on disk but DB is empty after sync!")

            except Exception as exc:
                logger.error(f"Failed to initialize Borg Universe during startup: {exc}")
        else:
            logger.warning("Supabase not configured, skipping Borg Universe initialization.")

    @app.exception_handler(StarletteHTTPException)
    async def render_html_exception(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api") or request.url.path in {"/health", "/docs", "/openapi.json"}:
            return await http_exception_handler(request, exc)

        ctx = get_ui_context()
        ctx.update({
            "active": "",
            "title": "Node not ready",
            "status_code": exc.status_code,
            "detail": exc.detail,
        })
        return templates.TemplateResponse(
            request,
            "pages/error.html",
            ctx,
            status_code=exc.status_code,
        )

    @app.get("/", response_class=HTMLResponse, tags=["system"])
    async def root(request: Request) -> Response:
        try:
            orchestration = OrchestrationSettingsStore(settings.borg_root).load()
        except RuntimeError:
            orchestration = None
        
        client = SupabaseRestClient(settings)
        projects: list[dict] = []
        tasks: list[dict] = []
        project_error = ""
        task_error = ""
        try:
            projects = ProjectRepository(client).list_projects()
        except SupabaseRestError as exc:
            project_error = str(exc)
        try:
            tasks = TaskRepository(client).list_tasks()
        except SupabaseRestError as exc:
            task_error = str(exc)

        processed_task_count = sum(1 for task in tasks if task.get("status") in {"done", "review_required"})
        active_task_count = sum(1 for task in tasks if task.get("status") == "running")
        needs_input_tasks = _ordered_attention_tasks(tasks, "needs_input")
        review_tasks = [task for task in tasks if task.get("status") == "review_required"][:5]

        ctx = get_ui_context(client)
        ctx.update({
            "active": "home",
            "agents_root_name": settings.agents_root.name,
            "skills_root_name": settings.skills_root.name,
            "environment": settings.environment,
            "app_version": settings.app_version,
            "projects": projects,
            "project_count": len(projects),
            "processed_task_count": processed_task_count,
            "active_task_count": active_task_count,
            "needs_input_count": len(needs_input_tasks),
            "current_input_task": needs_input_tasks[0] if needs_input_tasks else None,
            "next_input_tasks": needs_input_tasks[1:5],
            "review_required_count": len(review_tasks),
            "review_tasks": review_tasks,
            "task_error": task_error,
            "project_types": PROJECT_TYPES,
            "project_error": project_error,
            "auto_refresh_seconds": 10,
            "agent_system": (
                orchestration.agent_selection.agent_system.replace("_", " ").title()
                if orchestration
                else "Not set"
            ),
            "local_model_endpoint": (
                f"{orchestration.local_model.ip_address}:{orchestration.local_model.port}"
                if orchestration
                else "Not set"
            ),
        })

        return templates.TemplateResponse(request, "pages/home.html", ctx)

    @app.get("/projects/new", response_class=HTMLResponse, tags=["system"])
    async def new_project(request: Request) -> Response:
        ctx = get_ui_context()
        ctx.update({
            "active": "home",
            "project_types": PROJECT_TYPES,
        })
        return templates.TemplateResponse(request, "pages/projects_new.html", ctx)

    @app.get("/projects", response_class=HTMLResponse, tags=["system"])
    async def projects_overview(request: Request) -> Response:
        logger = logging.getLogger("borg_universe")
        client = SupabaseRestClient(settings)
        try:
            projects = ProjectRepository(client).list_projects(include_inactive=True)
            project_error = ""
        except SupabaseRestError as exc:
            projects = []
            project_error = str(exc)

        try:
            # We explicitly fetch the items that are currently in the registry
            agents = BorgRegistryRepository(client, "agents").list_items()
            skills = BorgRegistryRepository(client, "skills").list_items()
            
            logger.info(f"Projects Overview: Loaded {len(agents)} agents and {len(skills)} skills from DB.")
            
            # If DB is empty but we have files, this might be a fresh start or sync issue
            if not agents or not skills:
                from app.services.borg_scanner import scan_agents, scan_skills
                if not agents:
                    disk_agents = scan_agents(settings)
                    if disk_agents:
                        logger.warning(f"DB agents empty, but {len(disk_agents)} found on disk. Syncing...")
                        BorgRegistryRepository(client, "agents").sync(disk_agents)
                        agents = BorgRegistryRepository(client, "agents").list_items()
                if not skills:
                    disk_skills = scan_skills(settings)
                    if disk_skills:
                        logger.warning(f"DB skills empty, but {len(disk_skills)} found on disk. Syncing...")
                        BorgRegistryRepository(client, "skills").sync(disk_skills)
                        skills = BorgRegistryRepository(client, "skills").list_items()
            
            # Fetch existing bindings and local .claude state
            binding_repo = ProjectRegistryBindingRepository(client)
            bindings_available = True
            try:
                for p in projects:
                    p["bindings"] = binding_repo.list_for_project(p["id"])
                    p["bound_agents"] = [b["unit_name"] for b in p["bindings"] if b["unit_type"] == "agent"]
                    p["bound_skills"] = [b["unit_name"] for b in p["bindings"] if b["unit_type"] == "skill"]
            except SupabaseRestError as exc:
                if _is_missing_project_registry_bindings_table(exc):
                    logger.warning("project_registry_bindings table is missing. Continuing without stored bindings.")
                    bindings_available = False
                else:
                    raise

            for p in projects:
                if not bindings_available:
                    p["bindings"] = []
                    p["bound_agents"] = []
                    p["bound_skills"] = []

                # Check local .claude state
                p["local_agents"] = []
                p["local_skills"] = []
                project_dir = p.get("project_directory", "").strip()
                if project_dir:
                    runtime_root = _resolve_project_runtime_root(project_dir)
                    claude_dir = runtime_root / ".claude" if runtime_root is not None else Path(project_dir).absolute() / ".claude"
                    agents_dir = claude_dir / "agents"
                    skills_dir = claude_dir / "skills"
                    if agents_dir.is_dir():
                        p["local_agents"] = [f.stem for f in agents_dir.glob("*.md")]
                    if skills_dir.is_dir():
                        p["local_skills"] = [
                            d.name for d in skills_dir.iterdir()
                            if d.is_dir() and (d / "SKILL.md").is_file()
                        ]
        except SupabaseRestError as exc:
            logger.error(f"Error loading registry items for projects: {exc}")
            # If DB fetch fails, we try to fall back to an empty list rather than erroring out the whole page
            agents = agents if 'agents' in locals() else []
            skills = skills if 'skills' in locals() else []

        ctx = get_ui_context(client)
        ctx.update({
            "active": "projects",
            "projects": projects,
            "project_count": len(projects),
            "project_error": project_error,
            "agents": agents,
            "skills": skills,
        })

        return templates.TemplateResponse(request, "pages/projects.html", ctx)

    @app.get("/projects/import", response_class=HTMLResponse, tags=["system"])
    async def import_projects_page(request: Request) -> Response:
        ctx = get_ui_context()
        scanned = scan_drive_for_projects(settings.workbench_root)
        try:
            existing = ProjectRepository(SupabaseRestClient(settings)).list_projects(include_inactive=True)
            existing_ids = {p["id"] for p in existing}
        except SupabaseRestError:
            existing_ids = set()

        # Filter out already imported projects
        available = [p for p in scanned if p["id"] not in existing_ids]

        ctx.update({
            "active": "projects",
            "projects": available,
            "workbench_path": str(settings.workbench_root),
        })
        return templates.TemplateResponse(request, "pages/projects_import.html", ctx)

    @app.post("/projects/import", tags=["system"])
    async def do_import_projects(request: Request) -> RedirectResponse:
        form = await request.form()
        selected_ids = form.getlist("project_ids")
        
        scanned = scan_drive_for_projects(settings.workbench_root)
        to_import = [p for p in scanned if p["id"] in selected_ids]
        
        repo = ProjectRepository(SupabaseRestClient(settings))
        for p in to_import:
            project = ProjectCreate(
                id=p["id"],
                name=p["name"],
                description=p["description"],
                project_type=p["project_type"],
                project_directory=p["path"],
                active=True
            )
            try:
                repo.create_project(project)
            except Exception:
                # Skip if already exists or other error
                pass
        
        ids_query = ",".join(selected_ids)
        return RedirectResponse(f"/projects/import/tasks?project_ids={ids_query}", status_code=303)

    @app.get("/projects/import/tasks", response_class=HTMLResponse, tags=["system"])
    async def import_tasks_page(request: Request) -> Response:
        ctx = get_ui_context()
        project_ids = request.query_params.get("project_ids", "").split(",")
        project_ids = [pid for pid in project_ids if pid]
        
        repo = ProjectRepository(SupabaseRestClient(settings))
        projects = []
        for pid in project_ids:
            p = repo.get_project(pid)
            if p:
                projects.append(p)
        
        workflow_store = WorkflowStore(settings.workflows_root)
        workflows = workflow_store.list_workflows()
        
        ctx.update({
            "active": "projects",
            "projects": projects,
            "workflows": workflows,
        })
        return templates.TemplateResponse(request, "pages/projects_import_tasks.html", ctx)

    @app.post("/projects/import/tasks", tags=["system"])
    async def do_import_tasks(request: Request) -> RedirectResponse:
        form = await request.form()
        project_ids = form.getlist("project_ids")
        
        task_repo = TaskRepository(SupabaseRestClient(settings))
        
        for pid in project_ids:
            title = form.get(f"title_{pid}")
            workflow_id = form.get(f"workflow_id_{pid}")
            description = form.get(f"description_{pid}", "")
            platform = form.get(f"platform_{pid}")
            mcu = form.get(f"mcu_{pid}")
            board = form.get(f"board_{pid}")
            topic = form.get(f"topic_{pid}")
            
            if title and workflow_id:
                task = TaskCreate(
                    title=title,
                    description=description,
                    project_id=pid,
                    workflow_id=workflow_id,
                    target_platform=_optional(platform),
                    target_mcu=_optional(mcu),
                    board=_optional(board),
                    topic=_optional(topic),
                    requested_by="System Import"
                )
                try:
                    task_repo.create_task(task)
                except Exception:
                    # Log or handle error
                    pass
                    
        return RedirectResponse("/tasks", status_code=303)

    @app.post("/projects", tags=["system"])
    async def create_project(request: Request) -> RedirectResponse:
        form = await _read_urlencoded_form(request)
        name = form.get("name", "").strip()
        project = ProjectCreate(
            id=_slugify_project_id(form.get("id") or name),
            name=name,
            description=form.get("description", "").strip(),
            project_type=form.get("project_type", "stm").strip() or "stm",
            project_directory=form.get("project_directory", "").strip(),
            pycharm_mcp_enabled=form.get("pycharm_mcp_enabled") == "on",
            pycharm_mcp_sse_url=_optional(form.get("pycharm_mcp_sse_url")),
            pycharm_mcp_stream_url=_optional(form.get("pycharm_mcp_stream_url")),
            default_platform=_optional(form.get("default_platform")),
            default_mcu=_optional(form.get("default_mcu")),
            default_board=_optional(form.get("default_board")),
            default_topic=_optional(form.get("default_topic")),
            active=True,
        )
        ProjectRepository(SupabaseRestClient(settings)).create_project(project)
        return RedirectResponse("/projects/new", status_code=303)

    @app.post("/projects/{project_id}/bind", tags=["system"])
    async def bind_project_units(project_id: str, request: Request) -> RedirectResponse:
        form = await request.form()
        agent_names = form.getlist("agent_names")
        skill_names = form.getlist("skill_names")
        
        units = []
        for name in agent_names:
            units.append({"name": name, "type": "agent"})
        for name in skill_names:
            units.append({"name": name, "type": "skill"})
            
        client = SupabaseRestClient(settings)
        repo = ProjectRegistryBindingRepository(client)
        project_repo = ProjectRepository(client)
        
        try:
            repo.unbind_all(project_id)
            if units:
                repo.bind_units(project_id, units)
        except SupabaseRestError as exc:
            if _is_missing_project_registry_bindings_table(exc):
                logging.getLogger("borg_universe").warning(
                    "project_registry_bindings table is missing. Continuing with filesystem copy only."
                )
            else:
                logging.getLogger("borg_universe").error(f"Error binding units: {exc}")
                return RedirectResponse("/projects", status_code=303)

        try:
            project = project_repo.get_project(project_id)
            if project:
                project_dir = project.get("project_directory", "").strip()
                if not project_dir:
                    logging.getLogger("borg_universe").warning(f"Project {project_id} has no project_directory set. Skipping copy to .claude.")
                else:
                    base_path = _resolve_project_runtime_root(project_dir)
                    if base_path is None:
                        raise RuntimeError(
                            "Project directory is not accessible from the running service. "
                            "Check WORKBENCH_HOST_ROOT / WORKBENCH_CONTAINER_ROOT and the Docker volume mount."
                        )
                    logging.getLogger("borg_universe").info(f"Base path for .claude: {base_path}")
                    claude_dir = base_path / ".claude"

                    # Keep the layout compatible with Claude Code project-local assets.
                    agents_dir = claude_dir / "agents"
                    skills_dir = claude_dir / "skills"
                    agents_dir.mkdir(parents=True, exist_ok=True)
                    skills_dir.mkdir(parents=True, exist_ok=True)
                    logging.getLogger("borg_universe").info(f"Target .claude directory: {claude_dir}")

                    # Copy agents
                    for name in agent_names:
                        source_file = settings.agents_root.absolute() / f"{name}.md"
                        logging.getLogger("borg_universe").info(f"Trying to copy agent {name} from {source_file}")
                        if source_file.exists():
                            target_file = agents_dir / f"{name}.md"
                            shutil.copy2(source_file, target_file)
                            logging.getLogger("borg_universe").info(f"Copied agent {name} to {target_file}")
                        else:
                            fallback_file = (settings.borg_root / "agents").absolute() / f"{name}.md"
                            logging.getLogger("borg_universe").info(f"Trying fallback for agent {name}: {fallback_file}")
                            if fallback_file.exists():
                                 target_file = agents_dir / f"{name}.md"
                                 shutil.copy2(fallback_file, target_file)
                                 logging.getLogger("borg_universe").info(f"Copied agent {name} from BORG fallback to {target_file}")
                            else:
                                 found = False
                                 for root_dir in [settings.agents_root, settings.borg_root / "agents"]:
                                     if not root_dir.exists(): continue
                                     matches = list(root_dir.glob(f"**/{name}.md"))
                                     if matches:
                                         shutil.copy2(matches[0], agents_dir / f"{name}.md")
                                         logging.getLogger("borg_universe").info(f"Copied agent {name} from deep search: {matches[0]}")
                                         found = True
                                         break
                                 if not found:
                                     logging.getLogger("borg_universe").warning(f"Agent source file {source_file} not found (tried fallbacks too)")

                    # Copy skills
                    for name in skill_names:
                        source_skill_dir = settings.skills_root.absolute() / name
                        logging.getLogger("borg_universe").info(f"Trying to copy skill {name} from {source_skill_dir}")
                        if not (source_skill_dir.exists() and source_skill_dir.is_dir()):
                            source_skill_dir = (settings.borg_root / "skills").absolute() / name
                            logging.getLogger("borg_universe").info(f"Trying fallback for skill {name}: {source_skill_dir}")

                        if source_skill_dir.exists() and source_skill_dir.is_dir():
                            target_skill_dir = skills_dir / name
                            if target_skill_dir.exists():
                                shutil.rmtree(target_skill_dir)
                            shutil.copytree(source_skill_dir, target_skill_dir)
                            logging.getLogger("borg_universe").info(f"Copied skill {name} to {target_skill_dir}")
                        else:
                            found = False
                            for root_dir in [settings.skills_root, settings.borg_root / "skills"]:
                                if not root_dir.exists(): continue
                                matches = [d for d in root_dir.glob(f"**/{name}") if d.is_dir()]
                                if matches:
                                    target_skill_dir = skills_dir / name
                                    if target_skill_dir.exists():
                                        shutil.rmtree(target_skill_dir)
                                    shutil.copytree(matches[0], target_skill_dir)
                                    logging.getLogger("borg_universe").info(f"Copied skill {name} from deep search: {matches[0]}")
                                    found = True
                                    break
                            if not found:
                                logging.getLogger("borg_universe").warning(f"Skill source directory for {name} not found in any location")
        except Exception as exc:
            logging.getLogger("borg_universe").error(f"Unexpected error during bind and copy: {exc}")
            
        return RedirectResponse("/projects", status_code=303)

    @app.post("/projects/{project_id}/unbind", tags=["system"])
    async def unbind_project_units(project_id: str) -> RedirectResponse:
        client = SupabaseRestClient(settings)
        repo = ProjectRegistryBindingRepository(client)
        try:
            repo.unbind_all(project_id)
        except SupabaseRestError as exc:
            print(f"Error unbinding units: {exc}")
        return RedirectResponse("/projects", status_code=303)

    @app.post("/projects/{project_id}/delete", tags=["system"])
    async def delete_project(project_id: str) -> RedirectResponse:
        client = SupabaseRestClient(settings)
        repo = ProjectRepository(client)
        try:
            project = repo.get_project(project_id)
            if not project:
                raise StarletteHTTPException(status_code=404, detail="Project not found")
            task_repo = TaskRepository(client)
            task_ids = [task["id"] for task in task_repo.list_for_project(project_id)]
            for task_id in task_ids:
                client.request("DELETE", "task_events", query={"task_id": f"eq.{task_id}"}, prefer="return=minimal")
                client.request("DELETE", "artifacts", query={"task_id": f"eq.{task_id}"}, prefer="return=minimal")
            task_repo.delete_for_project(project_id)
            ProjectSpecRepository(client).delete_for_project(project_id)
            client.request(
                "DELETE",
                "mcp_access_logs",
                query={"project_id": f"eq.{project_id}"},
                prefer="return=minimal",
            )
            deleted = repo.delete_project(project_id)
        except SupabaseRestError as exc:
            raise StarletteHTTPException(status_code=503, detail=str(exc)) from exc
        if not deleted:
            raise StarletteHTTPException(status_code=404, detail="Project not found")
        return RedirectResponse("/projects", status_code=303)

    return app


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _slugify_project_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "project"


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolve_project_runtime_root(project_directory: str) -> Path | None:
    text = project_directory.strip()
    if not text:
        return None

    mapped = _map_workbench_path(text)
    if mapped is not None:
        return mapped

    try:
        candidate = Path(text).expanduser()
    except Exception:
        return None
    return candidate if candidate.exists() else None


def _map_workbench_path(host_path: str) -> Path | None:
    normalized_host = host_path.replace("\\", "/").rstrip("/")
    if not normalized_host:
        return None

    host_root = os.getenv("WORKBENCH_HOST_ROOT", r"D:\Workbench").replace("\\", "/").rstrip("/")
    container_root = os.getenv("WORKBENCH_CONTAINER_ROOT", str(get_settings().workbench_root)).replace("\\", "/").rstrip("/")

    if normalized_host.lower() == host_root.lower():
        return Path(container_root)

    prefix = host_root + "/"
    if normalized_host.lower().startswith(prefix.lower()):
        suffix = normalized_host[len(host_root) + 1 :]
        return Path(f"{container_root}/{suffix}") if suffix else Path(container_root)

    inferred = _infer_workbench_container_path(normalized_host, container_root)
    if inferred is not None:
        return inferred

    if normalized_host.startswith("/"):
        absolute = Path(normalized_host)
        return absolute if absolute.exists() else None

    return None


def _infer_workbench_container_path(normalized_host: str, container_root: str) -> Path | None:
    marker = "/workbench/"
    lowered = normalized_host.lower()
    idx = lowered.find(marker)
    if idx != -1:
        suffix = normalized_host[idx + len(marker) :]
        return Path(f"{container_root}/{suffix}") if suffix else Path(container_root)

    if lowered.endswith("/workbench"):
        return Path(container_root)

    return None


def _is_missing_project_registry_bindings_table(exc: SupabaseRestError) -> bool:
    text = str(exc)
    return exc.status_code == 404 or "42P01" in text or "project_registry_bindings" in text


def _ordered_attention_tasks(tasks: list[dict], status_value: str) -> list[dict]:
    selected = [task for task in tasks if task.get("status") == status_value]
    return sorted(selected, key=lambda task: str(task.get("updated_at") or task.get("created_at") or ""))


app = create_app()
