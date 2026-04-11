from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, get_settings
from app.db.repositories import BorgRegistryRepository, TaskRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.borg import EnableUpdate
from app.services.borg_scanner import scan_agents, scan_skills
from app.services.mock_agent import MockAgentError, run_mock_agent

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
async def agents_page(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _registry_page("agents", settings)


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
async def skills_page(settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    return _registry_page("skills", settings)


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


def _registry_page(kind: str, settings: Settings) -> HTMLResponse:
    try:
        items = _repo(kind, settings).list_items()
    except SupabaseRestError as exc:
        return HTMLResponse(_page(kind.title(), f"<p class='error'>{escape(str(exc))}</p>"), status_code=503)

    rows = "".join(_registry_row(kind, item) for item in items)
    if not rows:
        rows = "<tr><td colspan='7'>No entries registered. Run scan.</td></tr>"
    content = f"""
    <nav>
      <a href="/tasks">Tasks</a>
      <a href="/knowledge">Knowledge</a>
      <a href="/rules">Rules</a>
      <a href="/examples">Examples</a>
      <a href="/agents">Agents</a>
      <a href="/skills">Skills</a>
    </nav>
    <section>
      <h1>{escape(kind.title())}</h1>
      <form method="post" action="/{escape(kind)}/sync">
        <button type="submit">Scan local {escape(kind)}</button>
      </form>
      <table>
        <thead>
          <tr><th>Name</th><th>Enabled</th><th>Supabase lookup</th><th>Scopes</th><th>Description</th><th>Path</th><th>Action</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """
    return HTMLResponse(_page(kind.title(), content))


def _registry_row(kind: str, item: dict) -> str:
    scopes = ", ".join(item.get("allowed_supabase_scopes") or [])
    enabled = "yes" if item.get("enabled") else "no"
    lookup = "required" if item.get("requires_supabase_project_lookup") else "not required"
    return f"""
    <tr>
      <td>{escape(item.get('name') or '')}</td>
      <td>{enabled}</td>
      <td>{lookup}</td>
      <td>{escape(scopes)}</td>
      <td>{escape(item.get('description') or '')}</td>
      <td>{escape(item.get('path') or '')}</td>
      <td><form method="post" action="/{escape(kind)}/{escape(item.get('name') or '')}/toggle"><button type="submit">Toggle</button></form></td>
    </tr>
    """


def _page(title: str, content: str) -> str:
    return f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{escape(title)} - Borg Universe</title>
      <style>
        body {{ margin: 0; font-family: Arial, sans-serif; color: #1b1f23; background: #f6f8fa; }}
        main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px; }}
        nav {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }}
        h1 {{ margin: 0 0 16px; }}
        form {{ margin: 0 0 16px; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8dee4; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 10px; border-bottom: 1px solid #d8dee4; text-align: left; vertical-align: top; }}
        th {{ background: #eef2f5; }}
        button {{ padding: 8px 12px; border: 0; border-radius: 6px; background: #116329; color: #fff; font: inherit; cursor: pointer; }}
        .error {{ padding: 12px; border: 1px solid #cf222e; border-radius: 6px; background: #ffebe9; color: #cf222e; }}
        a {{ color: #0969da; }}
      </style>
    </head>
    <body><main>{content}</main></body>
    </html>
    """
