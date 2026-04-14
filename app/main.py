import re
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.repositories import ProjectRepository, ProjectSpecRepository, TaskRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.projects import PROJECT_TYPES, ProjectCreate
from app.services.orchestration_settings_store import OrchestrationSettingsStore
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

    @app.exception_handler(StarletteHTTPException)
    async def render_html_exception(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api") or request.url.path in {"/health", "/docs", "/openapi.json"}:
            return await http_exception_handler(request, exc)

        return templates.TemplateResponse(
            request,
            "pages/error.html",
            {
                "active": "",
                "title": "Node not ready",
                "status_code": exc.status_code,
                "detail": exc.detail,
                "system_status": "intervention",
            },
            status_code=exc.status_code,
        )

    @app.get("/", response_class=HTMLResponse, tags=["system"])
    async def root(request: Request) -> Response:
        try:
            orchestration = OrchestrationSettingsStore(settings.borg_root).load()
        except RuntimeError:
            orchestration = None
        projects: list[dict] = []
        tasks: list[dict] = []
        project_error = ""
        task_error = ""
        try:
            projects = ProjectRepository(SupabaseRestClient(settings)).list_projects()
        except SupabaseRestError as exc:
            project_error = str(exc)
        try:
            tasks = TaskRepository(SupabaseRestClient(settings)).list_tasks()
        except SupabaseRestError as exc:
            task_error = str(exc)

        processed_task_count = sum(1 for task in tasks if task.get("status") in {"done", "review_required"})
        active_task_count = sum(1 for task in tasks if task.get("status") == "running")
        needs_input_tasks = _ordered_attention_tasks(tasks, "needs_input")
        review_tasks = [task for task in tasks if task.get("status") == "review_required"][:5]
        return templates.TemplateResponse(
            request,
            "pages/home.html",
            {
                "active": "home",
                "system_status": "configured" if settings.supabase_configured else "intervention",
                "supabase_configured": settings.supabase_configured,
                "mcp_configured": bool(settings.mcp_server_url),
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
            },
        )

    @app.get("/projects/new", response_class=HTMLResponse, tags=["system"])
    async def new_project(request: Request) -> Response:
        return templates.TemplateResponse(
            request,
            "pages/projects_new.html",
            {
                "active": "home",
                "system_status": "configured" if settings.supabase_configured else "intervention",
                "supabase_configured": settings.supabase_configured,
                "mcp_configured": bool(settings.mcp_server_url),
                "project_types": PROJECT_TYPES,
            },
        )

    @app.get("/projects", response_class=HTMLResponse, tags=["system"])
    async def projects_overview(request: Request) -> Response:
        try:
            projects = ProjectRepository(SupabaseRestClient(settings)).list_projects(include_inactive=True)
            project_error = ""
        except SupabaseRestError as exc:
            projects = []
            project_error = str(exc)
        return templates.TemplateResponse(
            request,
            "pages/projects.html",
            {
                "active": "projects",
                "system_status": "configured" if settings.supabase_configured else "intervention",
                "supabase_configured": settings.supabase_configured,
                "mcp_configured": bool(settings.mcp_server_url),
                "projects": projects,
                "project_count": len(projects),
                "project_error": project_error,
            },
        )

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


def _ordered_attention_tasks(tasks: list[dict], status_value: str) -> list[dict]:
    selected = [task for task in tasks if task.get("status") == status_value]
    return sorted(selected, key=lambda task: str(task.get("updated_at") or task.get("created_at") or ""))


app = create_app()
