import re
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.repositories import ProjectRepository, TaskRepository
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
                "review_required_count": len(review_tasks),
                "review_tasks": review_tasks,
                "task_error": task_error,
                "project_types": PROJECT_TYPES,
                "project_error": project_error,
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


app = create_app()
