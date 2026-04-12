from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.config import Settings, get_settings
from app.services.workflow_store import WorkflowStore, WorkflowStoreError
from app.ui import templates

router = APIRouter()


def get_workflow_store(settings: Annotated[Settings, Depends(get_settings)]) -> WorkflowStore:
    return WorkflowStore(settings.workflows_root)


def _workflow_progress(store: WorkflowStore, workflows: list) -> dict[str, dict[str, int | None]]:
    progress: dict[str, dict[str, int | None]] = {}
    for workflow in workflows:
        stages = store.build_stages(workflow)
        active_index: int | None = None
        for index, stage in enumerate(stages):
            task_statuses = [task.status for node in stage.nodes for task in node.tasks]
            if not task_statuses or any(task_status != "done" for task_status in task_statuses):
                active_index = index
                break
        next_index = active_index + 1 if active_index is not None and active_index + 1 < len(stages) else None
        progress[workflow.id] = {"active": active_index, "next": next_index}
    return progress


@router.get("/api/workflows")
async def list_workflows(store: Annotated[WorkflowStore, Depends(get_workflow_store)]) -> list[dict]:
    try:
        return [workflow.model_dump() for workflow in store.list_workflows()]
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, store: Annotated[WorkflowStore, Depends(get_workflow_store)]) -> dict:
    try:
        workflow = store.get_workflow(workflow_id)
    except WorkflowStoreError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow.model_dump()


@router.get("/workflows", response_class=HTMLResponse)
async def workflows_dashboard(
    request: Request,
    store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> HTMLResponse:
    try:
        workflows = store.list_workflows()
    except WorkflowStoreError as exc:
        return HTMLResponse(str(exc), status_code=422)

    metrics = [
        {"label": "Workflows", "value": len(workflows)},
        {"label": "Nodes", "value": sum(len(workflow.nodes) for workflow in workflows)},
        {"label": "Parallel phases", "value": sum(1 for workflow in workflows for step in workflow.steps if step.mode == "parallel")},
        {"label": "YAML path", "value": store.root.name},
    ]

    return templates.TemplateResponse(
        request,
        "pages/workflows.html",
        {
            "active": "workflows",
            "workflows": workflows,
            "metrics": metrics,
            "workflow_count": len(workflows),
            "empty_title": "No workflows yet",
            "empty_message": "Place YAML files in BORG/workflows to make workflow summaries visible.",
        },
    )


@router.get("/workflows/settings", response_class=HTMLResponse)
async def workflow_settings_page(
    request: Request,
    store: Annotated[WorkflowStore, Depends(get_workflow_store)],
    file: str | None = None,
) -> HTMLResponse:
    try:
        files = store.list_workflow_files()
        selected_file = file or (files[0] if files else "workflow.yaml")
        yaml_content = store.read_yaml(selected_file) if selected_file in files else _default_workflow_yaml()
    except WorkflowStoreError as exc:
        return HTMLResponse(str(exc), status_code=422)

    return _workflow_settings_response(
        request,
        store,
        files=files,
        selected_file=selected_file,
        yaml_content=yaml_content,
        message="",
        status_code=200,
    )


@router.post("/workflows/settings")
async def save_workflow_settings(
    request: Request,
    store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> Response:
    form = await _read_urlencoded_form(request)
    filename = (form.get("filename") or "workflow.yaml").strip()
    yaml_content = form.get("yaml_content") or ""

    try:
        store.save_yaml(filename, yaml_content)
    except WorkflowStoreError as exc:
        return _workflow_settings_response(
            request,
            store,
            files=store.list_workflow_files(),
            selected_file=filename,
            yaml_content=yaml_content,
            message=str(exc),
            status_code=422,
        )

    return RedirectResponse(f"/workflows/settings?file={quote(filename)}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/workflows/{workflow_id}", response_class=HTMLResponse)
async def workflow_detail_page(
    request: Request,
    workflow_id: str,
    store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> HTMLResponse:
    try:
        workflow = store.get_workflow(workflow_id)
    except WorkflowStoreError as exc:
        return HTMLResponse(str(exc), status_code=422)

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    return templates.TemplateResponse(
        request,
        "pages/workflow_detail.html",
        {
            "active": "workflows",
            "workflow": workflow,
            "workflow_stages": store.build_stages(workflow),
            "workflow_progress": _workflow_progress(store, [workflow])[workflow.id],
            "workflow_yaml": store.format_workflow(workflow),
            "workflow_file": workflow.source_file or f"{workflow.id}.yaml",
            "metrics": [
                {"label": "Nodes", "value": len(workflow.nodes)},
                {"label": "Steps", "value": len(workflow.steps)},
                {"label": "Source file", "value": workflow.source_file or f"{workflow.id}.yaml"},
                {"label": "Status", "value": workflow.status},
            ],
            "workflow_count": 1,
            "empty_title": "Workflow not found",
            "empty_message": "The selected workflow does not exist.",
        },
    )


@router.post("/workflows/{workflow_id}")
async def save_workflow_detail(
    workflow_id: str,
    request: Request,
    store: Annotated[WorkflowStore, Depends(get_workflow_store)],
) -> Response:
    form = await _read_urlencoded_form(request)
    workflow = store.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    filename = workflow.source_file or f"{workflow.id}.yaml"
    yaml_content = form.get("yaml_content", "")

    try:
        store.save_yaml(filename, yaml_content)
    except WorkflowStoreError as exc:
        return templates.TemplateResponse(
            request,
            "pages/workflow_detail.html",
            {
                "active": "workflows",
                "workflow": workflow,
                "workflow_stages": store.build_stages(workflow),
                "workflow_progress": _workflow_progress(store, [workflow])[workflow.id],
                "workflow_yaml": yaml_content,
                "workflow_file": filename,
                "metrics": [
                    {"label": "Nodes", "value": len(workflow.nodes)},
                    {"label": "Steps", "value": len(workflow.steps)},
                    {"label": "Source file", "value": filename},
                    {"label": "Status", "value": workflow.status},
                ],
                "workflow_count": 1,
                "empty_title": "Workflow not found",
                "empty_message": "The selected workflow does not exist.",
                "message": str(exc),
            },
            status_code=422,
        )

    return RedirectResponse(f"/workflows/{quote(workflow_id)}", status_code=status.HTTP_303_SEE_OTHER)


def _workflow_settings_response(
    request: Request,
    store: WorkflowStore,
    *,
    files: list[str],
    selected_file: str,
    yaml_content: str,
    message: str,
    status_code: int,
) -> HTMLResponse:
    metrics = [
        {"label": "Files", "value": len(files)},
        {"label": "Selected", "value": selected_file},
        {"label": "YAML path", "value": store.root.name},
        {"label": "Status", "value": "valid" if not message else "needs edit"},
    ]
    return templates.TemplateResponse(
        request,
        "pages/workflow_settings.html",
        {
            "active": "workflows",
            "files": files,
            "selected_file": selected_file,
            "yaml_content": yaml_content,
            "message": message,
            "metrics": metrics,
            "workflow_count": len(files),
            "empty_title": "No workflow files yet",
            "empty_message": "Save this draft to create the first workflow YAML file.",
        },
        status_code=status_code,
    )


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _default_workflow_yaml() -> str:
    return """id: workflow-draft
title: Workflow Draft
description: Define the workflow facts, nodes, tasks, and execution steps.
status: draft
entry_node: coordinator
nodes:
  - id: coordinator
    borg_name: Coordinator
    role: coordinator
    agent: codex
    tasks:
      - id: intake
        title: Intake
        prompt: Review the request and prepare the next step.
        status: draft
steps:
  - id: intake
    title: Start
    mode: sequential
    nodes:
      - coordinator
"""
