from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, get_settings
from app.db.repositories import ArtifactRepository, BorgRegistryRepository, McpAuditRepository, ProjectRepository, TaskRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.tasks import TASK_STATUSES, TaskCreate, TaskStatusUpdate
from app.services.workflow_store import WorkflowStore, WorkflowStoreError
from app.ui import templates

router = APIRouter()

DEFAULT_PROJECTS: list[dict[str, str]] = [
    {"id": "example-1", "name": "Example 1", "default_platform": "STM32", "project_directory": ""},
    {"id": "example-2", "name": "Example 2", "default_platform": "Nordic", "project_directory": ""},
]


def get_task_repository(settings: Annotated[Settings, Depends(get_settings)]) -> TaskRepository:
    try:
        return TaskRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_artifact_repository(settings: Annotated[Settings, Depends(get_settings)]) -> ArtifactRepository:
    try:
        return ArtifactRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_project_repository(settings: Annotated[Settings, Depends(get_settings)]) -> ProjectRepository:
    try:
        return ProjectRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_workflow_store(settings: Annotated[Settings, Depends(get_settings)]) -> WorkflowStore:
    return WorkflowStore(settings.workflows_root)


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


@router.post("/api/tasks/{task_id}/queue")
async def queue_task(task_id: str, repo: Annotated[TaskRepository, Depends(get_task_repository)]) -> dict:
    try:
        task = repo.update_status(task_id, "queued")
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    repo.add_event(task_id, "task_queued", "Task queued for worker processing.", {})
    return task


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_dashboard(
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    project_repo: Annotated[ProjectRepository, Depends(get_project_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> HTMLResponse:
    settings = get_settings()
    try:
        client = SupabaseRestClient(settings)
        tasks = repo.list_tasks()
        agents = BorgRegistryRepository(client, "agents").list_items()
        skills = BorgRegistryRepository(client, "skills").list_items()
    except Exception as exc:
        return HTMLResponse(str(exc), status_code=503)

    try:
        projects = project_repo.list_projects()
    except SupabaseRestError:
        projects = DEFAULT_PROJECTS
    try:
        workflows = workflow_store.list_workflows()
    except WorkflowStoreError:
        workflows = []

    counts = {status_value: 0 for status_value in TASK_STATUSES}
    for task in tasks:
        counts[task.get("status", "draft")] = counts.get(task.get("status", "draft"), 0) + 1
    metrics = [
        {"label": "Queued", "value": counts.get("queued", 0)},
        {"label": "Running", "value": counts.get("running", 0)},
        {"label": "Review", "value": counts.get("review_required", 0)},
        {"label": "Needs input", "value": counts.get("needs_input", 0)},
    ]

    project_labels = {project["id"]: project["name"] for project in projects}
    workflow_labels = {workflow.id: workflow.title for workflow in workflows}

    return templates.TemplateResponse(
        request,
        "pages/tasks.html",
        {
            "active": "tasks",
            "tasks": tasks,
            "projects": projects,
            "workflows": workflows,
            "project_labels": project_labels,
            "workflow_labels": workflow_labels,
            "metrics": metrics,
            "task_count": len(tasks),
            "agent_count": len(agents),
            "skill_count": len(skills),
            "workflow_count": len(workflows),
            "system_status": "configured" if settings.supabase_configured else "intervention",
            "supabase_configured": settings.supabase_configured,
            "mcp_configured": bool(settings.mcp_server_url),
            "empty_title": "No tasks yet",
            "empty_message": "Create the first task to start the worker flow.",
        },
    )


@router.post("/tasks")
async def create_task_from_form(
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    project_repo: Annotated[ProjectRepository, Depends(get_project_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    project_id = _optional(form.get("project_id"))
    workflow_id = _optional(form.get("workflow_id"))
    project = _get_project_defaults(project_repo, project_id)
    workflow_title = _get_workflow_title(workflow_store, workflow_id)
    task = TaskCreate(
        title=_generated_task_title(project, workflow_title, form.get("description", "")),
        description=form.get("description", "").strip(),
        project_id=project_id,
        workflow_id=workflow_id,
        target_platform=_optional(form.get("target_platform")) or _optional(project.get("default_platform")),
        target_mcu=_optional(form.get("target_mcu")) or _optional(project.get("default_mcu")),
        board=_optional(form.get("board")) or _optional(project.get("default_board")),
        local_path=_optional(form.get("local_path")) or _optional(project.get("project_directory")),
        pycharm_mcp_enabled=_bool_form(form.get("pycharm_mcp_enabled")) or bool(project.get("pycharm_mcp_enabled")),
        topic=_optional(project.get("default_topic")),
        requested_by=_optional(form.get("requested_by")),
        assigned_agent="local-llm",
        assigned_skill=workflow_id,
    )
    try:
        created = repo.create_task(task)
        repo.add_event(
            created["id"],
            "workflow_selected",
            "Workflow selected for local LLM processing.",
            {"workflow_id": workflow_id, "workflow_title": workflow_title, "agent": "local-llm"},
        )
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc
    return RedirectResponse(f"/tasks/{created['id']}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(
    task_id: str,
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    artifact_repo: Annotated[ArtifactRepository, Depends(get_artifact_repository)],
    project_repo: Annotated[ProjectRepository, Depends(get_project_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> HTMLResponse:
    settings = get_settings()
    try:
        client = SupabaseRestClient(settings)
        task = repo.get_task(task_id)
        if not task:
            return HTMLResponse("Task not found", status_code=404)
        events = repo.list_events(task_id)
        artifacts = artifact_repo.list_for_task(task_id)
        agents = BorgRegistryRepository(client, "agents").list_items()
        skills = BorgRegistryRepository(client, "skills").list_items()
        tasks_list = repo.list_tasks()
    except Exception as exc:
        return HTMLResponse(str(exc), status_code=503)

    try:
        projects = project_repo.list_projects()
    except SupabaseRestError:
        projects = DEFAULT_PROJECTS
    try:
        workflows = workflow_store.list_workflows()
    except WorkflowStoreError:
        workflows = []

    project_labels = {project["id"]: project["name"] for project in projects}
    workflow_labels = {workflow.id: workflow.title for workflow in workflows}

    return templates.TemplateResponse(
        request,
        "pages/task_detail.html",
        {
            "active": "tasks",
            "task": task,
            "events": events,
            "artifacts": artifacts,
            "projects": projects,
            "project_labels": project_labels,
            "workflow_labels": workflow_labels,
            "statuses": TASK_STATUSES,
            "task_count": len(tasks_list),
            "agent_count": len(agents),
            "skill_count": len(skills),
            "workflow_count": len(workflows),
            "system_status": "configured" if settings.supabase_configured else "intervention",
            "supabase_configured": settings.supabase_configured,
            "mcp_configured": bool(settings.mcp_server_url),
            "detail_fields": [
                ("Project", "project_id"),
                ("Workflow", "workflow_id"),
                ("Description", "description"),
                ("Platform", "target_platform"),
                ("MCU", "target_mcu"),
                ("Board", "board"),
                ("Local path", "local_path"),
                ("PyCharm MCP", "pycharm_mcp_enabled"),
                ("Requested by", "requested_by"),
                ("Created", "created_at"),
                ("Updated", "updated_at"),
            ],
            "empty_title": "No data yet",
            "empty_message": "The worker creates history entries and artifacts once the task is processed.",
        },
    )


def get_mcp_audit_repository(settings: Annotated[Settings, Depends(get_settings)]) -> McpAuditRepository:
    try:
        return McpAuditRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/workflow", response_class=HTMLResponse)
async def task_workflow(
    task_id: str,
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
    mcp_repo: Annotated[McpAuditRepository, Depends(get_mcp_audit_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    try:
        task = repo.get_task(task_id)
        if not task:
            return HTMLResponse("Task not found", status_code=404)
        events = repo.list_events(task_id)
        logs = mcp_repo.list_logs({"task_id": task_id})
    except SupabaseRestError as exc:
        return HTMLResponse(str(exc), status_code=503)
    except Exception as exc:
        # Log unexpected errors to help debugging
        print(f"Error in task_workflow: {exc}")
        import traceback
        traceback.print_exc()
        return HTMLResponse(f"Internal Server Error: {str(exc)}", status_code=500)

    workflow = None
    stages = []
    if task.get("workflow_id"):
        workflow = workflow_store.get_workflow(task["workflow_id"])
        if workflow:
            stages = workflow_store.build_stages(workflow)

    return templates.TemplateResponse(
        request,
        "pages/task_workflow.html",
        {
            "active": "tasks",
            "task": task,
            "events": events,
            "logs": logs,
            "workflow": workflow,
            "stages": stages,
        },
    )


def _client(settings: Settings) -> SupabaseRestClient:
    try:
        return SupabaseRestClient(settings)
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/tasks/{task_id}/review", response_class=HTMLResponse)
async def review_task(
    task_id: str,
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    artifact_repo: Annotated[ArtifactRepository, Depends(get_artifact_repository)],
    project_repo: Annotated[ProjectRepository, Depends(get_project_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> HTMLResponse:
    settings = get_settings()
    try:
        client = SupabaseRestClient(settings)
        task = repo.get_task(task_id)
        if not task:
            return HTMLResponse("Task not found", status_code=404)
        events = repo.list_events(task_id)
        artifacts = artifact_repo.list_for_task(task_id)
        agents = BorgRegistryRepository(client, "agents").list_items()
        skills = BorgRegistryRepository(client, "skills").list_items()
        tasks_list = repo.list_tasks()
        workflow_count = len(workflow_store.list_workflows())
    except Exception as exc:
        return HTMLResponse(str(exc), status_code=503)

    try:
        projects = project_repo.list_projects()
    except SupabaseRestError:
        projects = DEFAULT_PROJECTS
    try:
        workflows = workflow_store.list_workflows()
    except WorkflowStoreError:
        workflows = []

    project_labels = {project["id"]: project["name"] for project in projects}
    workflow_labels = {workflow.id: workflow.title for workflow in workflows}
    llm_review = _latest_llm_review(events)
    llm_transcript = _build_llm_transcript(events)
    llm_human_output = _latest_llm_human_output(events, llm_transcript, llm_review)
    workflow_stage_options = _workflow_stage_options(workflow_store, task.get("workflow_id"))
    suggested_resume_stage_index = _next_resume_stage_index(repo, workflow_store, task_id, events)

    return templates.TemplateResponse(
        request,
        "pages/task_review.html",
        {
            "active": "tasks",
            "task": task,
            "events": events,
            "artifacts": artifacts,
            "llm_review": llm_review,
            "llm_transcript": llm_transcript,
            "llm_human_output": llm_human_output,
            "projects": projects,
            "project_labels": project_labels,
            "workflow_labels": workflow_labels,
            "statuses": TASK_STATUSES,
            "task_count": len(tasks_list),
            "agent_count": len(agents),
            "skill_count": len(skills),
            "workflow_count": workflow_count,
            "system_status": "configured" if settings.supabase_configured else "intervention",
            "supabase_configured": settings.supabase_configured,
            "mcp_configured": bool(settings.mcp_server_url),
            "review_actions": [
                {"value": "save", "label": "Save review"},
                {"value": "confirm", "label": "Confirm and continue"},
                {"value": "start_implementation", "label": "Start implementation"},
                {"value": "request_changes", "label": "Request changes"},
                {"value": "cancel", "label": "Cancel task"},
            ],
            "workflow_stage_options": workflow_stage_options,
            "suggested_resume_stage_index": suggested_resume_stage_index,
            "detail_fields": [
                ("Project", "project_id"),
                ("Workflow", "workflow_id"),
                ("Description", "description"),
                ("Title", "title"),
                ("Platform", "target_platform"),
                ("MCU", "target_mcu"),
                ("Board", "board"),
                ("Local path", "local_path"),
                ("PyCharm MCP", "pycharm_mcp_enabled"),
                ("Requested by", "requested_by"),
                ("Created", "created_at"),
                ("Updated", "updated_at"),
            ],
            "empty_title": "No data yet",
            "empty_message": "The worker creates history entries and artifacts once the task is processed.",
        },
    )


@router.post("/tasks/{task_id}/review")
async def submit_task_review(
    task_id: str,
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    action = form.get("action") or form.get("review_action") or "save"

    updates: dict[str, object] = {}
    for field in ("title", "description", "target_platform", "target_mcu", "board", "local_path", "requested_by"):
        value = _optional(form.get(field))
        if value is not None:
            updates[field] = value
    if "pycharm_mcp_enabled" in form:
        updates["pycharm_mcp_enabled"] = _bool_form(form.get("pycharm_mcp_enabled"))
    repo.update_fields(task_id, updates)

    review_notes = _optional(form.get("review_notes"))
    events = repo.list_events(task_id)
    if updates:
        repo.add_event(
            task_id,
            "review_modified",
            "Review changes were applied to the task.",
            {"changes": updates},
        )
    if review_notes:
        repo.add_event(
            task_id,
            "review_noted",
            "Review notes were recorded.",
            {"notes": review_notes},
        )

    if action in {"confirm", "start_implementation"}:
        repo.add_event(
            task_id,
            "review_confirmed",
            "Review confirmed; task will continue through the workflow chain.",
            {"notes": review_notes, "changes": updates, "action": action},
        )
        if action == "start_implementation":
            resume_stage_index = _implementation_trigger_stage_index(workflow_store, task_id, repo)
        else:
            resume_stage_index = _selected_resume_stage_index(form, workflow_store, task_id, repo)
            if resume_stage_index is None:
                resume_stage_index = _next_resume_stage_index(repo, workflow_store, task_id, events)
        if resume_stage_index is None:
            repo.add_event(
                task_id,
                "workflow_completed",
                "Review confirmed, but the selected workflow has no remaining levels to execute.",
                {"notes": review_notes, "changes": updates},
            )
            repo.update_status(task_id, "done")
            return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)
        repo.add_event(
            task_id,
            "workflow_resumed",
            "Review completed; the selected workflow stage is queued.",
            {
                "notes": review_notes,
                "changes": updates,
                "next_step": "workflow_nodes",
                "resume_stage_index": resume_stage_index,
                "action": action,
            },
        )
        _queue_task(repo, task_id)
        return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)
    elif action == "request_changes":
        repo.update_status(task_id, "needs_input")
        repo.add_event(
            task_id,
            "review_changes_requested",
            "Review requested changes and paused the workflow chain.",
            {"notes": review_notes, "changes": updates},
        )
    elif action == "cancel":
        repo.update_status(task_id, "cancelled")
        repo.add_event(
            task_id,
            "review_cancelled",
            "Review cancelled the task and stopped the workflow chain.",
            {"notes": review_notes, "changes": updates},
        )
        return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        repo.update_status(task_id, "review_required")
        repo.add_event(
            task_id,
            "review_saved",
            "Review saved without advancing the workflow chain.",
            {"notes": review_notes, "changes": updates},
        )

    return RedirectResponse(f"/tasks/{task_id}/review", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/status")
async def update_task_status_from_form(
    task_id: str,
    request: Request,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    status_value = form.get("status", "draft")
    if status_value == "queued":
        _queue_task(repo, task_id)
    else:
        repo.update_status(task_id, status_value)
    return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/queue")
async def queue_task_from_form(
    task_id: str,
    repo: Annotated[TaskRepository, Depends(get_task_repository)],
) -> RedirectResponse:
    _queue_task(repo, task_id)
    return RedirectResponse(f"/tasks/{task_id}", status_code=status.HTTP_303_SEE_OTHER)


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _bool_form(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _get_project_defaults(repo: ProjectRepository, project_id: str | None) -> dict:
    if not project_id:
        return {}
    try:
        return repo.get_project(project_id) or {}
    except SupabaseRestError:
        return {}


def _get_workflow_title(store: WorkflowStore, workflow_id: str | None) -> str | None:
    if not workflow_id:
        return None
    try:
        workflow = store.get_workflow(workflow_id)
    except WorkflowStoreError:
        return None
    return workflow.title if workflow else workflow_id


def _generated_task_title(project: dict, workflow_title: str | None, description: str) -> str:
    project_name = _optional(project.get("name")) or "Selected project"
    if workflow_title:
        return f"{project_name} - {workflow_title}"[:200]
    first_line = _optional(description.splitlines()[0] if description else None)
    if first_line:
        return f"{project_name} - {first_line}"[:200]
    return f"{project_name} task"


def _queue_task(repo: TaskRepository, task_id: str) -> dict | None:
    task = repo.update_status(task_id, "queued")
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    repo.add_event(task_id, "task_queued", "Task queued for worker processing.", {})
    return task


def _workflow_stage_options(workflow_store: WorkflowStore, workflow_id: str | None) -> list[dict[str, object]]:
    if not workflow_id:
        return []
    try:
        workflow = workflow_store.get_workflow(str(workflow_id))
    except WorkflowStoreError:
        return []
    if not workflow:
        return []
    options: list[dict[str, object]] = []
    for index, stage in enumerate(workflow_store.build_stages(workflow)):
        step_id = workflow.steps[index].id if index < len(workflow.steps) else stage.title
        options.append(
            {
                "index": index,
                "id": step_id,
                "title": stage.title,
            }
        )
    return options


def _selected_resume_stage_index(
    form: dict[str, str],
    workflow_store: WorkflowStore,
    task_id: str,
    repo: TaskRepository,
) -> int | None:
    raw_value = _optional(form.get("resume_stage_index"))
    if raw_value is None:
        return None
    try:
        selected = int(raw_value)
    except ValueError:
        return None

    task = repo.get_task(task_id)
    workflow_id = str((task or {}).get("workflow_id") or "")
    if not workflow_id:
        return None
    try:
        workflow = workflow_store.get_workflow(workflow_id)
    except WorkflowStoreError:
        return None
    if not workflow:
        return None
    stage_count = len(workflow_store.build_stages(workflow))
    if selected < 0 or selected >= stage_count:
        return None
    return selected


def _implementation_trigger_stage_index(
    workflow_store: WorkflowStore,
    task_id: str,
    repo: TaskRepository,
) -> int | None:
    task = repo.get_task(task_id)
    workflow_id = str((task or {}).get("workflow_id") or "")
    if not workflow_id:
        return None
    try:
        workflow = workflow_store.get_workflow(workflow_id)
    except WorkflowStoreError:
        return None
    if not workflow:
        return None
    stages = workflow_store.build_stages(workflow)
    for index, stage in enumerate(stages):
        step_id = workflow.steps[index].id if index < len(workflow.steps) else ""
        if step_id == "implementation-trigger-phase":
            return index
        for node in stage.nodes:
            if node.id == "implementation-trigger" or node.role == "implementation_trigger":
                return index
    for index, stage in enumerate(stages):
        step_id = workflow.steps[index].id if index < len(workflow.steps) else ""
        if step_id == "implementation-phase":
            return index
    return None


def _next_resume_stage_index(
    repo: TaskRepository,
    workflow_store: WorkflowStore,
    task_id: str,
    events: list[dict[str, object]],
) -> int | None:
    task = repo.get_task(task_id)
    workflow_id = str((task or {}).get("workflow_id") or "")
    stage_count: int | None = None
    if workflow_id:
        try:
            workflow = workflow_store.get_workflow(workflow_id)
            if workflow:
                stage_count = len(workflow_store.build_stages(workflow))
        except WorkflowStoreError:
            stage_count = None

    for event in reversed(events):
        if str(event.get("event_type") or "") != "workflow_stage_completed":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        raw_next_index = payload.get("next_stage_index")
        if raw_next_index is None:
            return None
        try:
            next_index = int(raw_next_index)
        except (TypeError, ValueError):
            break
        if stage_count is not None and next_index >= stage_count:
            return None
        return next_index

    return 1 if stage_count is None or stage_count > 1 else None


def _latest_llm_review(events: list[dict[str, object]]) -> dict[str, str] | None:
    for event in reversed(events):
        event_type = str(event.get("event_type") or "")
        if event_type == "llm_processing_completed":
            payload = event.get("payload") or {}
            summary = ""
            if isinstance(payload, dict):
                summary = str(payload.get("summary") or "")
            if not summary:
                summary = str(event.get("message") or "")
            return {
                "summary": summary,
                "created_at": str(event.get("created_at") or ""),
                "source": event_type,
            }
        if event_type == "agent_result_ready":
            payload = event.get("payload") or {}
            if isinstance(payload, dict):
                summary = str(event.get("message") or "")
                return {
                    "summary": summary,
                    "created_at": str(event.get("created_at") or ""),
                "source": event_type,
            }
    return None


def _build_llm_transcript(events: list[dict[str, object]]) -> list[dict[str, str]]:
    transcript: list[dict[str, str]] = []
    by_iteration: dict[int, dict[str, str]] = {}
    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        iteration_raw = payload.get("iteration")
        try:
            iteration = int(iteration_raw)
        except (TypeError, ValueError):
            continue

        entry = by_iteration.setdefault(iteration, {"iteration": str(iteration)})
        if event_type in {"llm_request", "llm_iteration_completed"}:
            entry["prompt"] = str(payload.get("prompt") or "")
        if event_type in {"llm_response", "llm_iteration_completed"}:
            entry["response"] = str(payload.get("response") or payload.get("output") or "")
        if event_type == "llm_response":
            entry["parsed"] = str(payload.get("parsed") or "")

    for iteration in sorted(by_iteration):
        transcript.append(by_iteration[iteration])
    return transcript


def _latest_llm_human_output(
    events: list[dict[str, object]],
    transcript: list[dict[str, str]],
    llm_review: dict[str, str] | None,
) -> str:
    for event in reversed(events):
        if str(event.get("event_type") or "") != "llm_processing_completed":
            continue
        payload = event.get("payload") or {}
        if isinstance(payload, dict):
            human_review_text = str(payload.get("human_review_text") or "").strip()
            if human_review_text:
                return human_review_text
    if transcript:
        lines: list[str] = []
        for entry in transcript:
            lines.append(f"Iteration {entry.get('iteration')}")
            if entry.get("prompt"):
                lines.append("Prompt:")
                lines.append(entry["prompt"])
            if entry.get("response"):
                lines.append("Response:")
                lines.append(entry["response"])
            lines.append("")
        return "\n".join(lines).strip()
    if llm_review:
        return llm_review.get("summary", "")
    return ""
