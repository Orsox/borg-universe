from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, get_settings
from app.db.repositories import TaskRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.tasks import TASK_STATUSES, TaskCreate, TaskStatusUpdate

router = APIRouter()


def get_task_repository(settings: Annotated[Settings, Depends(get_settings)]) -> TaskRepository:
    try:
        return TaskRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _handle_repository_error(exc: SupabaseRestError) -> HTTPException:
    code = exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE
    if code >= 500:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/api/tasks")
async def list_tasks(repo: Annotated[TaskRepository, Depends(get_task_repository)]) -> list[dict]:
    try:
        return repo.list_tasks()
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc


@router.post("/api/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> dict:
    try:
        return repo.create_task(payload)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str, repo: Annotated[TaskRepository, Depends(get_task_repository)]) -> dict:
    try:
        task = repo.get_task(task_id)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("/api/tasks/{task_id}/events")
async def list_task_events(
    task_id: str,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> list[dict]:
    try:
        if not repo.get_task(task_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        return repo.list_events(task_id)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc


@router.patch("/api/tasks/{task_id}/status")
async def update_task_status(
    task_id: str,
    payload: TaskStatusUpdate,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> dict:
    try:
        task = repo.update_status(task_id, payload.status)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_dashboard(repo: Annotated[TaskRepository, Depends(get_task_repository)]) -> HTMLResponse:
    try:
        tasks = repo.list_tasks()
    except SupabaseRestError as exc:
        return HTMLResponse(_page("Tasks", f"<p class='error'>{escape(str(exc))}</p>"), status_code=503)

    rows = "\n".join(_task_row(task) for task in tasks)
    if not rows:
        rows = "<tr><td colspan='5'>No tasks yet.</td></tr>"

    content = f"""
    <section>
      <h1>Tasks</h1>
      <form method="post" action="/tasks" class="task-form">
        <label>Title <input name="title" required maxlength="200"></label>
        <label>Description <textarea name="description" rows="4"></textarea></label>
        <div class="grid">
          <label>Platform <input name="target_platform"></label>
          <label>MCU <input name="target_mcu"></label>
          <label>Board <input name="board"></label>
          <label>Topic <input name="topic"></label>
          <label>Requested by <input name="requested_by"></label>
          <label>Agent <input name="assigned_agent"></label>
          <label>Skill <input name="assigned_skill"></label>
        </div>
        <button type="submit">Create task</button>
      </form>
    </section>
    <section>
      <h2>Task queue</h2>
      <table>
        <thead>
          <tr><th>Title</th><th>Status</th><th>Topic</th><th>Agent</th><th>Updated</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """
    return HTMLResponse(_page("Tasks", content))


@router.post("/tasks")
async def create_task_from_form(
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    task = TaskCreate(
        title=form.get("title", "Untitled task").strip(),
        description=form.get("description", "").strip(),
        target_platform=_optional(form.get("target_platform")),
        target_mcu=_optional(form.get("target_mcu")),
        board=_optional(form.get("board")),
        topic=_optional(form.get("topic")),
        requested_by=_optional(form.get("requested_by")),
        assigned_agent=_optional(form.get("assigned_agent")),
        assigned_skill=_optional(form.get("assigned_skill")),
    )
    created = repo.create_task(task)
    return RedirectResponse(f"/tasks/{created['id']}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(
    task_id: str,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> HTMLResponse:
    try:
        task = repo.get_task(task_id)
        if not task:
            return HTMLResponse(_page("Task not found", "<p class='error'>Task not found.</p>"), status_code=404)
        events = repo.list_events(task_id)
    except SupabaseRestError as exc:
        return HTMLResponse(_page("Task error", f"<p class='error'>{escape(str(exc))}</p>"), status_code=503)

    fields = "".join(
        _detail_row(label, task.get(key))
        for label, key in (
            ("Description", "description"),
            ("Platform", "target_platform"),
            ("MCU", "target_mcu"),
            ("Board", "board"),
            ("Topic", "topic"),
            ("Requested by", "requested_by"),
            ("Agent", "assigned_agent"),
            ("Skill", "assigned_skill"),
            ("Created", "created_at"),
            ("Updated", "updated_at"),
        )
    )
    options = "\n".join(
        f"<option value='{status_value}' {'selected' if status_value == task['status'] else ''}>{status_value}</option>"
        for status_value in TASK_STATUSES
    )
    event_items = "\n".join(_event_item(event) for event in events) or "<li>No events yet.</li>"
    content = f"""
    <p><a href="/tasks">Back to tasks</a></p>
    <section>
      <h1>{escape(task['title'])}</h1>
      <p><span class="badge">{escape(task['status'])}</span></p>
      <form method="post" action="/tasks/{escape(task_id)}/status" class="status-form">
        <label>Status <select name="status">{options}</select></label>
        <button type="submit">Update status</button>
      </form>
      <form method="post" action="/tasks/{escape(task_id)}/mock-agent-run" class="status-form">
        <button type="submit">Run mock agent</button>
      </form>
      <dl>{fields}</dl>
    </section>
    <section>
      <h2>Events</h2>
      <ol class="events">{event_items}</ol>
    </section>
    """
    return HTMLResponse(_page(task["title"], content))


@router.post("/tasks/{task_id}/status")
async def update_task_status_from_form(
    task_id: str,
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    repo.update_status(task_id, form.get("status", "draft"))
    return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _task_row(task: dict) -> str:
    return f"""
    <tr>
      <td><a href="/tasks/{escape(task['id'])}">{escape(task['title'])}</a></td>
      <td><span class="badge">{escape(task['status'])}</span></td>
      <td>{escape(task.get('topic') or '')}</td>
      <td>{escape(task.get('assigned_agent') or '')}</td>
      <td>{escape(task.get('updated_at') or '')}</td>
    </tr>
    """


def _detail_row(label: str, value: object) -> str:
    return f"<dt>{escape(label)}</dt><dd>{escape(str(value or ''))}</dd>"


def _event_item(event: dict) -> str:
    return (
        f"<li><strong>{escape(event['event_type'])}</strong> "
        f"<span>{escape(event['created_at'])}</span><br>{escape(event['message'])}</li>"
    )


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
        main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px; }}
        section {{ margin-bottom: 32px; }}
        h1, h2 {{ margin: 0 0 16px; }}
        form, table, dl, .events {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; }}
        form {{ padding: 16px; }}
        label {{ display: block; margin-bottom: 12px; font-weight: 600; }}
        input, textarea, select {{ box-sizing: border-box; width: 100%; margin-top: 6px; padding: 10px; border: 1px solid #d0d7de; border-radius: 6px; font: inherit; }}
        button {{ padding: 10px 14px; border: 0; border-radius: 6px; background: #116329; color: #fff; font: inherit; cursor: pointer; }}
        table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #d8dee4; text-align: left; vertical-align: top; }}
        th {{ background: #eef2f5; }}
        tr:last-child td {{ border-bottom: 0; }}
        dl {{ display: grid; grid-template-columns: minmax(120px, 220px) 1fr; margin: 0; }}
        dt, dd {{ margin: 0; padding: 12px; border-bottom: 1px solid #d8dee4; }}
        dt {{ font-weight: 700; background: #eef2f5; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 6px; background: #ddf4ff; color: #0969da; font-weight: 700; }}
        .events {{ padding: 16px 16px 16px 36px; }}
        .events li {{ margin-bottom: 14px; }}
        .events span {{ color: #57606a; }}
        .error {{ padding: 12px; border: 1px solid #cf222e; border-radius: 6px; background: #ffebe9; color: #cf222e; }}
        a {{ color: #0969da; }}
      </style>
    </head>
    <body>
      <main>{content}</main>
    </body>
    </html>
    """
