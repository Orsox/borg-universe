from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services.local_llm_client import LocalLlmClient, LocalLlmClientError
from app.services.orchestration_settings_store import (
    AGENT_SYSTEMS,
    AgentSelectionSettings,
    ExecutionSettings,
    LocalModelSettings,
    OrchestrationSettings,
    OrchestrationSettingsStore,
)
from app.ui import templates

router = APIRouter()


def get_orchestration_store(settings: Annotated[Settings, Depends(get_settings)]) -> OrchestrationSettingsStore:
    return OrchestrationSettingsStore(settings.borg_root)


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}


@router.get("/orchestration", response_class=HTMLResponse)
async def orchestration_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[OrchestrationSettingsStore, Depends(get_orchestration_store)],
) -> HTMLResponse:
    try:
        orchestration = store.load()
    except RuntimeError:
        orchestration = OrchestrationSettings()
    return templates.TemplateResponse(
        request,
        "pages/orchestration.html",
        {
            "active": "orchestration",
            "agent_systems": AGENT_SYSTEMS,
            "settings": orchestration,
            "environment": settings.environment,
            "task_count": 0,
            "workflow_count": 0,
            "agent_count": 0,
            "skill_count": 0,
            "mcp_configured": bool(settings.mcp_server_url),
        },
    )


@router.post("/orchestration")
async def save_orchestration(
    request: Request,
    store: Annotated[OrchestrationSettingsStore, Depends(get_orchestration_store)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    try:
        agent_selection = AgentSelectionSettings(
            agent_system=form.get("agent_system", "codex").strip() or "codex",
            agent_name=_optional(form.get("agent_name")),
            notes=_optional(form.get("notes")),
        )
        execution = ExecutionSettings(
            max_parallel_tasks=int(form.get("max_parallel_tasks", "4") or "4"),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    store.save(agent_selection=agent_selection, execution=execution)
    return RedirectResponse("/orchestration", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/orchestration/local-model", response_class=HTMLResponse)
async def local_model_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[OrchestrationSettingsStore, Depends(get_orchestration_store)],
) -> HTMLResponse:
    try:
        orchestration = store.load()
    except RuntimeError:
        orchestration = OrchestrationSettings()
    return templates.TemplateResponse(
        request,
        "pages/local_model.html",
        {
            "active": "local_model",
            "settings": orchestration,
            "environment": settings.environment,
            "task_count": 0,
            "workflow_count": 0,
            "agent_count": 0,
            "skill_count": 0,
            "mcp_configured": bool(settings.mcp_server_url),
        },
    )


@router.post("/orchestration/local-model")
async def save_local_model(
    request: Request,
    store: Annotated[OrchestrationSettingsStore, Depends(get_orchestration_store)],
) -> RedirectResponse:
    form = await _read_urlencoded_form(request)
    try:
        local_model = LocalModelSettings(
            ip_address=form.get("ip_address", "127.0.0.1").strip() or "127.0.0.1",
            port=int(form.get("port", "11434") or "11434"),
            api_key=_optional(form.get("api_key")),
            model_name=_optional(form.get("model_name")),
        )
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    store.save(local_model=local_model)
    return RedirectResponse("/orchestration/local-model", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api/orchestration/local-model/test")
async def test_local_model(
    request: Request,
    store: Annotated[OrchestrationSettingsStore, Depends(get_orchestration_store)],
) -> JSONResponse:
    form = await _read_urlencoded_form(request)
    prompt = form.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Prompt is required")

    try:
        orchestration = store.load()
        client = LocalLlmClient(orchestration.local_model)
        models = client.list_models()
        result = client.send_prompt(prompt)
    except RuntimeError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local model is not configured")
    except LocalLlmClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return JSONResponse(
        {
            "prompt": prompt,
            "reply": result["content"],
            "models": models,
            "endpoint": f"http://{orchestration.local_model.ip_address}:{orchestration.local_model.port}/v1/chat/completions",
        }
    )


async def _read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
