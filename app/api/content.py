from __future__ import annotations

from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.config import Settings, get_settings
from app.db.repositories import ContentRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.knowledge import CodeExampleCreate, KnowledgeEntryCreate, RuleCreate, split_csv
from app.ui import templates

router = APIRouter()

TABLES = {
    "knowledge": "knowledge_entries",
    "rules": "rules",
    "examples": "code_examples",
}

PAGE_CONFIG = {
    "knowledge": {
        "heading": "Knowledge",
        "list_path": "/knowledge",
        "active": "knowledge",
        "filters": ["platform", "mcu_family", "peripheral", "tags"],
        "columns": ["title", "platform", "mcu_family", "peripheral", "tags", "updated_at"],
        "empty_title": "No knowledge captured yet",
        "empty_message": "Create an entry or synchronize external sources later.",
        "fields": [
            {"name": "title", "label": "Title", "required": True},
            {"name": "domain", "label": "Domain"},
            {"name": "platform", "label": "Platform"},
            {"name": "mcu_family", "label": "MCU family"},
            {"name": "peripheral", "label": "Peripheral"},
            {"name": "source", "label": "Source"},
            {"name": "quality_level", "label": "Quality"},
            {"name": "tags", "label": "Tags"},
            {"name": "content", "label": "Content", "type": "textarea", "rows": 6, "required": True},
        ],
    },
    "rules": {
        "heading": "Rules",
        "list_path": "/rules",
        "active": "rules",
        "filters": ["scope", "severity", "applies_to"],
        "columns": ["name", "scope", "severity", "applies_to", "updated_at"],
        "empty_title": "No rules captured yet",
        "empty_message": "Rules will govern agent work and reviews later.",
        "fields": [
            {"name": "name", "label": "Name", "required": True},
            {"name": "scope", "label": "Scope"},
            {"name": "severity", "label": "Severity", "default": "info"},
            {"name": "applies_to", "label": "Applies to"},
            {"name": "rule_text", "label": "Rule text", "type": "textarea", "rows": 6, "required": True},
        ],
    },
    "examples": {
        "heading": "Code examples",
        "list_path": "/examples",
        "active": "examples",
        "filters": ["platform", "framework", "peripheral", "tags"],
        "columns": ["title", "platform", "framework", "language", "peripheral", "tags", "updated_at"],
        "empty_title": "No code examples captured yet",
        "empty_message": "Code examples can later be used by agents as implementation references.",
        "fields": [
            {"name": "title", "label": "Title", "required": True},
            {"name": "platform", "label": "Platform"},
            {"name": "framework", "label": "Framework"},
            {"name": "language", "label": "Language"},
            {"name": "peripheral", "label": "Peripheral"},
            {"name": "tags", "label": "Tags"},
            {"name": "code", "label": "Code", "type": "textarea", "rows": 8, "required": True},
            {"name": "explanation", "label": "Explanation", "type": "textarea", "rows": 4},
            {"name": "known_limitations", "label": "Known limitations", "type": "textarea", "rows": 4},
        ],
    },
}


def _repository(kind: str, settings: Settings) -> ContentRepository:
    if kind not in TABLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content type not found")
    try:
        return ContentRepository(SupabaseRestClient(settings), TABLES[kind])
    except SupabaseRestError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _handle_error(exc: SupabaseRestError) -> HTTPException:
    code = exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE
    if code >= 500:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/api/knowledge")
async def list_knowledge(
    settings: Annotated[Settings, Depends(get_settings)],
    platform: str | None = None,
    mcu_family: str | None = None,
    peripheral: str | None = None,
    tags: str | None = None,
) -> list[dict]:
    try:
        return _repository("knowledge", settings).list_items(
            {"platform": platform, "mcu_family": mcu_family, "peripheral": peripheral, "tags": tags}
        )
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


@router.post("/api/knowledge", status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    payload: KnowledgeEntryCreate,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    try:
        return _repository("knowledge", settings).create_item(payload)
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


@router.get("/api/knowledge/{item_id}")
async def get_knowledge(item_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return _get_api_item("knowledge", item_id, settings)


@router.put("/api/knowledge/{item_id}")
async def update_knowledge(
    item_id: str,
    payload: KnowledgeEntryCreate,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    return _update_api_item("knowledge", item_id, payload, settings)


@router.delete("/api/knowledge/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(item_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    _delete_api_item("knowledge", item_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/rules")
async def list_rules(
    settings: Annotated[Settings, Depends(get_settings)],
    scope: str | None = None,
    severity: str | None = None,
    applies_to: str | None = None,
) -> list[dict]:
    try:
        return _repository("rules", settings).list_items(
            {"scope": scope, "severity": severity, "applies_to": applies_to}
        )
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


@router.post("/api/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(payload: RuleCreate, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    try:
        return _repository("rules", settings).create_item(payload)
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


@router.get("/api/rules/{item_id}")
async def get_rule(item_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return _get_api_item("rules", item_id, settings)


@router.put("/api/rules/{item_id}")
async def update_rule(item_id: str, payload: RuleCreate, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return _update_api_item("rules", item_id, payload, settings)


@router.delete("/api/rules/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(item_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    _delete_api_item("rules", item_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/examples")
async def list_examples(
    settings: Annotated[Settings, Depends(get_settings)],
    platform: str | None = None,
    framework: str | None = None,
    peripheral: str | None = None,
    tags: str | None = None,
) -> list[dict]:
    try:
        return _repository("examples", settings).list_items(
            {"platform": platform, "framework": framework, "peripheral": peripheral, "tags": tags}
        )
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


@router.post("/api/examples", status_code=status.HTTP_201_CREATED)
async def create_example(
    payload: CodeExampleCreate,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    try:
        return _repository("examples", settings).create_item(payload)
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


@router.get("/api/examples/{item_id}")
async def get_example(item_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return _get_api_item("examples", item_id, settings)


@router.put("/api/examples/{item_id}")
async def update_example(
    item_id: str,
    payload: CodeExampleCreate,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    return _update_api_item("examples", item_id, payload, settings)


@router.delete("/api/examples/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_example(item_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    _delete_api_item("examples", item_id, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    filters = dict(request.query_params)
    return _list_page(request, "knowledge", filters, settings)


@router.post("/knowledge")
async def create_knowledge_from_form(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    form = await _read_form(request)
    payload = KnowledgeEntryCreate(
        title=form.get("title", "").strip(),
        domain=_optional(form.get("domain")),
        platform=_optional(form.get("platform")),
        mcu_family=_optional(form.get("mcu_family")),
        peripheral=_optional(form.get("peripheral")),
        content=form.get("content", "").strip(),
        source=_optional(form.get("source")),
        quality_level=_optional(form.get("quality_level")),
        tags=split_csv(form.get("tags")),
    )
    _repository("knowledge", settings).create_item(payload)
    return RedirectResponse("/knowledge", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    filters = dict(request.query_params)
    return _list_page(request, "rules", filters, settings)


@router.post("/rules")
async def create_rule_from_form(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    form = await _read_form(request)
    payload = RuleCreate(
        name=form.get("name", "").strip(),
        scope=_optional(form.get("scope")),
        severity=form.get("severity", "info").strip() or "info",
        rule_text=form.get("rule_text", "").strip(),
        applies_to=split_csv(form.get("applies_to")),
    )
    _repository("rules", settings).create_item(payload)
    return RedirectResponse("/rules", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/examples", response_class=HTMLResponse)
async def examples_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HTMLResponse:
    filters = dict(request.query_params)
    return _list_page(request, "examples", filters, settings)


@router.post("/examples")
async def create_example_from_form(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    form = await _read_form(request)
    payload = CodeExampleCreate(
        title=form.get("title", "").strip(),
        platform=_optional(form.get("platform")),
        framework=_optional(form.get("framework")),
        language=_optional(form.get("language")),
        peripheral=_optional(form.get("peripheral")),
        code=form.get("code", "").strip(),
        explanation=_optional(form.get("explanation")),
        known_limitations=_optional(form.get("known_limitations")),
        tags=split_csv(form.get("tags")),
    )
    _repository("examples", settings).create_item(payload)
    return RedirectResponse("/examples", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/knowledge/{item_id}/edit", response_class=HTMLResponse)
async def edit_knowledge_page(
    item_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    return _edit_page(request, "knowledge", item_id, settings)


@router.post("/knowledge/{item_id}/edit")
async def update_knowledge_from_form(
    item_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    form = await _read_form(request)
    payload = KnowledgeEntryCreate(
        title=form.get("title", "").strip(),
        domain=_optional(form.get("domain")),
        platform=_optional(form.get("platform")),
        mcu_family=_optional(form.get("mcu_family")),
        peripheral=_optional(form.get("peripheral")),
        content=form.get("content", "").strip(),
        source=_optional(form.get("source")),
        quality_level=_optional(form.get("quality_level")),
        tags=split_csv(form.get("tags")),
    )
    _repository("knowledge", settings).update_item(item_id, payload)
    return RedirectResponse("/knowledge", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/knowledge/{item_id}/delete")
async def delete_knowledge_from_form(
    item_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    _repository("knowledge", settings).delete_item(item_id)
    return RedirectResponse("/knowledge", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/rules/{item_id}/edit", response_class=HTMLResponse)
async def edit_rule_page(
    item_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    return _edit_page(request, "rules", item_id, settings)


@router.post("/rules/{item_id}/edit")
async def update_rule_from_form(
    item_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    form = await _read_form(request)
    payload = RuleCreate(
        name=form.get("name", "").strip(),
        scope=_optional(form.get("scope")),
        severity=form.get("severity", "info").strip() or "info",
        rule_text=form.get("rule_text", "").strip(),
        applies_to=split_csv(form.get("applies_to")),
    )
    _repository("rules", settings).update_item(item_id, payload)
    return RedirectResponse("/rules", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/rules/{item_id}/delete")
async def delete_rule_from_form(
    item_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    _repository("rules", settings).delete_item(item_id)
    return RedirectResponse("/rules", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/examples/{item_id}/edit", response_class=HTMLResponse)
async def edit_example_page(
    item_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    return _edit_page(request, "examples", item_id, settings)


@router.post("/examples/{item_id}/edit")
async def update_example_from_form(
    item_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    form = await _read_form(request)
    payload = CodeExampleCreate(
        title=form.get("title", "").strip(),
        platform=_optional(form.get("platform")),
        framework=_optional(form.get("framework")),
        language=_optional(form.get("language")),
        peripheral=_optional(form.get("peripheral")),
        code=form.get("code", "").strip(),
        explanation=_optional(form.get("explanation")),
        known_limitations=_optional(form.get("known_limitations")),
        tags=split_csv(form.get("tags")),
    )
    _repository("examples", settings).update_item(item_id, payload)
    return RedirectResponse("/examples", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/examples/{item_id}/delete")
async def delete_example_from_form(
    item_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    _repository("examples", settings).delete_item(item_id)
    return RedirectResponse("/examples", status_code=status.HTTP_303_SEE_OTHER)


def _get_api_item(kind: str, item_id: str, settings: Settings) -> dict:
    try:
        item = _repository(kind, settings).get_item(item_id)
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


def _update_api_item(
    kind: str,
    item_id: str,
    payload: KnowledgeEntryCreate | RuleCreate | CodeExampleCreate,
    settings: Settings,
) -> dict:
    try:
        item = _repository(kind, settings).update_item(item_id, payload)
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


def _delete_api_item(kind: str, item_id: str, settings: Settings) -> None:
    try:
        if not _repository(kind, settings).get_item(item_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
        _repository(kind, settings).delete_item(item_id)
    except SupabaseRestError as exc:
        raise _handle_error(exc) from exc


def _list_page(request: Request, kind: str, filters: dict[str, str], settings: Settings) -> HTMLResponse:
    config = PAGE_CONFIG[kind]
    try:
        items = _repository(kind, settings).list_items(filters)
    except SupabaseRestError as exc:
        return HTMLResponse(str(exc), status_code=503)

    return templates.TemplateResponse(
        request,
        "pages/content_list.html",
        {
            **config,
            "items": items,
            "filters": filters,
            "filter_fields": config["filters"],
            "form_fields": config["fields"],
            "empty_title": config["empty_title"],
            "empty_message": config["empty_message"],
        },
    )


def _edit_page(request: Request, kind: str, item_id: str, settings: Settings) -> HTMLResponse:
    config = PAGE_CONFIG[kind]
    try:
        item = _repository(kind, settings).get_item(item_id)
    except SupabaseRestError as exc:
        return HTMLResponse(str(exc), status_code=503)
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "pages/content_edit.html",
        {
            **config,
            "item": item,
            "form_fields": config["fields"],
        },
    )


async def _read_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
