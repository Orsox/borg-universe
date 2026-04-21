from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import Settings, get_settings
from app.db.repositories import IssueRepository, ProjectRepository, TaskRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.issues import ISSUE_PRIORITIES, ISSUE_STATUSES, IssueCreate
from app.models.tasks import TaskCreate
from app.services.workflow_store import WorkflowStore
from app.ui import templates

router = APIRouter()


def get_issue_repository(settings: Annotated[Settings, Depends(get_settings)]) -> IssueRepository:
    try:
        return IssueRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_project_repository(settings: Annotated[Settings, Depends(get_settings)]) -> ProjectRepository:
    try:
        return ProjectRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_task_repository(settings: Annotated[Settings, Depends(get_settings)]) -> TaskRepository:
    try:
        return TaskRepository(SupabaseRestClient(settings))
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def get_workflow_store(settings: Annotated[Settings, Depends(get_settings)]) -> WorkflowStore:
    return WorkflowStore(settings.workflows_root)


def _handle_repository_error(exc: SupabaseRestError) -> HTTPException:
    code = exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE
    if code >= 500:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=code, detail=str(exc))


# ── JSON API ──────────────────────────────────────────────────────────

@router.get("/api/issues")
async def list_issues_api(
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
    project_id: str | None = None,
) -> list[dict]:
    try:
        return repo.list_issues(project_id=project_id)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc


@router.post("/api/issues", status_code=status.HTTP_201_CREATED)
async def create_issue_api(
    payload: IssueCreate,
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
) -> dict:
    try:
        return repo.create_issue(payload)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc


@router.patch("/api/issues/{issue_id}/status")
async def update_issue_status_api(
    issue_id: str,
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
    new_status: str = "open",
) -> dict:
    if new_status not in ISSUE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status: {new_status}")
    try:
        issue = repo.update_status(issue_id, new_status)  # type: ignore[arg-type]
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    return issue


# ── HTML pages ────────────────────────────────────────────────────────

@router.get("/issues", response_class=HTMLResponse)
async def issues_page(
    request: Request,
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
    project_repo: Annotated[ProjectRepository, Depends(get_project_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
    project_id: str | None = None,
):
    try:
        issues = repo.list_issues(project_id=project_id)
        projects = project_repo.list_projects()
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc

    project_labels: dict[str, str] = {p["id"]: p["name"] for p in projects}

    workflow_store = WorkflowStore(settings.workflows_root)
    workflows = workflow_store.list_workflows()

    return templates.TemplateResponse(
        request,
        "pages/issues.html",
        {
            "active": "issues",
            "issues": issues,
            "projects": projects,
            "project_labels": project_labels,
            "selected_project_id": project_id or "",
            "statuses": ISSUE_STATUSES,
            "priorities": ISSUE_PRIORITIES,
            "workflows": workflows,
        },
    )


@router.post("/issues", response_class=HTMLResponse)
async def create_issue_page(
    request: Request,
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
):
    form = await request.form()
    title = (form.get("title") or "").strip()
    description = (form.get("description") or "").strip()
    project_id = form.get("project_id") or None
    priority = form.get("priority") or "medium"

    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required")

    issue = IssueCreate(
        title=title,
        description=description,
        project_id=project_id,
        priority=priority,  # type: ignore[arg-type]
    )

    try:
        repo.create_issue(issue)
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc

    redirect_url = "/issues"
    if project_id:
        redirect_url = f"/issues?project_id={project_id}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/issues/{issue_id}/status", response_class=HTMLResponse)
async def update_issue_status_page(
    request: Request,
    issue_id: str,
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
):
    form = await request.form()
    new_status = (form.get("status") or "").strip()
    if new_status not in ISSUE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status: {new_status}")

    try:
        issue = repo.update_status(issue_id, new_status)  # type: ignore[arg-type]
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc
    if not issue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")

    return RedirectResponse(url="/issues", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/issues/start-workflow", response_class=HTMLResponse)
async def start_workflow_for_issues(
    request: Request,
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    repo: Annotated[IssueRepository, Depends(get_issue_repository)],
    task_repo: Annotated[TaskRepository, Depends(get_task_repository)],
    project_repo: Annotated[ProjectRepository, Depends(get_project_repository)],
    workflow_store: Annotated[WorkflowStore, Depends(get_workflow_store)],
):
    form = await request.form()
    workflow_id = (form.get("workflow_id") or "").strip()
    issue_ids = form.getlist("issue_ids")

    if not workflow_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow is required")
    if not issue_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No issues selected")

    workflow = workflow_store.get_workflow(workflow_id)
    workflow_title = workflow.title if workflow else workflow_id

    try:
        for issue_id in issue_ids:
            issue = repo.get_issue(str(issue_id))
            if not issue:
                continue

            project = project_repo.get_project(issue["project_id"]) if issue.get("project_id") else None

            description = f"[Issue] {issue['title']}\n\n{issue.get('description', '')}".strip()
            task = TaskCreate(
                title=f"{workflow_title}: {issue['title']}",
                description=description,
                project_id=issue.get("project_id"),
                workflow_id=workflow_id,
                local_path=(project.get("project_directory") if project else None) or None,
                assigned_agent="local-llm",
                assigned_skill=workflow_id,
            )
            created = task_repo.create_task(task)
            task_repo.add_event(
                created["id"],
                "workflow_selected",
                f"Workflow '{workflow_title}' started for issue: {issue['title']}",
                {
                    "workflow_id": workflow_id,
                    "workflow_title": workflow_title,
                    "agent": "local-llm",
                    "issue_id": str(issue_id),
                    "issue_title": issue["title"],
                    "issue_priority": issue.get("priority", "medium"),
                },
            )

            repo.update_status(str(issue_id), "in_progress")
            _schedule_task_processing(background_tasks, settings, created["id"])
    except SupabaseRestError as exc:
        raise _handle_repository_error(exc) from exc

    return RedirectResponse(url="/issues", status_code=status.HTTP_303_SEE_OTHER)


def _schedule_task_processing(background_tasks: BackgroundTasks, settings: Settings, task_id: str) -> None:
    from app.main import _start_task_processing

    background_tasks.add_task(_start_task_processing, settings, task_id)
