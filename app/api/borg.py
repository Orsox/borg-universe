from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, get_settings
from app.db.repositories import BorgRegistryRepository, McpAuditRepository, TaskRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.borg import EnableUpdate
from app.services.borg_scanner import scan_agents, scan_skills
from app.services.mock_agent import MockAgentError, run_mock_agent
from app.ui import templates

router = APIRouter()


def _client(settings: Settings) -> SupabaseRestClient:
    try:
        return SupabaseRestClient(settings)
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _repo(kind: str, settings: Settings) -> BorgRegistryRepository:
    table = {"agents": "agents", "skills": "skills"}.get(kind)
    if not table:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registry type not found")
    return BorgRegistryRepository(_client(settings), table)


def _handle_supabase_error(exc: SupabaseRestError) -> HTTPException:
    code = exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE
    if code >= 500:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=code, detail=str(exc))


@router.post("/api/borg/sync")
async def sync_borg(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    try:
        agents = _repo("agents", settings).sync(scan_agents(settings))
        skills = _repo("skills", settings).sync(scan_skills(settings))
        return {"agents": len(agents), "skills": len(skills)}
    except SupabaseRestError as exc:
        raise _handle_supabase_error(exc) from exc


@router.get("/api/agents")
async def list_agents(settings: Annotated[Settings, Depends(get_settings)]) -> list[dict]:
    try:
        return _repo("agents", settings).list_items()
    except SupabaseRestError as exc:
        raise _handle_supabase_error(exc) from exc


@router.patch("/api/agents/{name}/enabled")
async def set_agent_enabled(
    name: str,
    payload: EnableUpdate,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    return _set_enabled("agents", name, payload.enabled, settings)


@router.get("/api/skills")
async def list_skills(settings: Annotated[Settings, Depends(get_settings)]) -> list[dict]:
    try:
        return _repo("skills", settings).list_items()
    except SupabaseRestError as exc:
        raise _handle_supabase_error(exc) from exc


@router.patch("/api/skills/{name}/enabled")
async def set_skill_enabled(
    name: str,
    payload: EnableUpdate,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    return _set_enabled("skills", name, payload.enabled, settings)


@router.post("/api/tasks/{task_id}/mock-agent-run")
async def run_mock_agent_for_task(
    task_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    try:
        return run_mock_agent(task_id, TaskRepository(_client(settings)), settings)
    except MockAgentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SupabaseRestError as exc:
        raise _handle_supabase_error(exc) from exc


@router.post("/tasks/{task_id}/mock-agent-run")
async def run_mock_agent_for_task_page(
    task_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    try:
        run_mock_agent(task_id, TaskRepository(_client(settings)), settings)
    except (MockAgentError, SupabaseRestError):
        pass
    return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _registry_page(request, "agents", settings)


@router.post("/agents/sync")
async def sync_agents_page(settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    _repo("agents", settings).sync(scan_agents(settings))
    return RedirectResponse("/agents", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/agents/{name}/toggle")
async def toggle_agent(name: str, settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    item = _repo("agents", settings).get_by_name(name)
    if item:
        _repo("agents", settings).set_enabled(name, not item["enabled"])
    return RedirectResponse("/agents", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _registry_page(request, "skills", settings)


@router.post("/skills/sync")
async def sync_skills_page(settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    _repo("skills", settings).sync(scan_skills(settings))
    return RedirectResponse("/skills", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/skills/{name}/toggle")
async def toggle_skill(name: str, settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    item = _repo("skills", settings).get_by_name(name)
    if item:
        _repo("skills", settings).set_enabled(name, not item["enabled"])
    return RedirectResponse("/skills", status_code=status.HTTP_303_SEE_OTHER)


def _set_enabled(kind: str, name: str, enabled: bool, settings: Settings) -> dict:
    try:
        item = _repo(kind, settings).set_enabled(name, enabled)
    except SupabaseRestError as exc:
        raise _handle_supabase_error(exc) from exc
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registry item not found")
    return item


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    filters = dict(request.query_params)
    try:
        logs = McpAuditRepository(_client(settings)).list_logs(filters)
    except SupabaseRestError as exc:
        return HTMLResponse(str(exc), status_code=503)

    return templates.TemplateResponse(
        request,
        "pages/audit.html",
        {
            "active": "audit",
            "logs": logs,
            "filters": filters,
            "filter_fields": ["agent_name", "skill_name", "tool_name", "task_id", "project_id"],
            "empty_title": "No MCP audit logs yet",
            "empty_message": "Logs appear when agents or MCP tools query Supabase data.",
        },
    )


def _registry_page(request: Request, kind: str, settings: Settings) -> HTMLResponse:
    try:
        items = _repo(kind, settings).list_items()
    except SupabaseRestError as exc:
        return HTMLResponse(str(exc), status_code=503)

    return templates.TemplateResponse(
        request,
        "pages/registry.html",
        {
            "active": kind,
            "kind": kind,
            "heading": "Agents" if kind == "agents" else "Skills",
            "items": items,
            "agent_count": len(items) if kind == "agents" else 0,
            "skill_count": len(items) if kind == "skills" else 0,
            "empty_title": "Nothing registered yet",
            "empty_message": "Run a local scan to load agents or skills from the BORG directory.",
        },
    )
