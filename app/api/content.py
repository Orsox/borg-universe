from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.config import Settings, get_settings
from app.db.repositories import ContentRepository
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from app.models.knowledge import CodeExampleCreate, KnowledgeEntryCreate, RuleCreate, split_csv

router = APIRouter()

TABLES = {
    "knowledge": "knowledge_entries",
    "rules": "rules",
    "examples": "code_examples",
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
    return _list_page("knowledge", filters, settings)


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
    return _list_page("rules", filters, settings)


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
    return _list_page("examples", filters, settings)


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


def _list_page(kind: str, filters: dict[str, str], settings: Settings) -> HTMLResponse:
    try:
        items = _repository(kind, settings).list_items(filters)
    except SupabaseRestError as exc:
        return HTMLResponse(_page(kind.title(), f"<p class='error'>{escape(str(exc))}</p>"), status_code=503)

    content = _nav()
    if kind == "knowledge":
        content += _knowledge_form(filters)
        content += _items_table(items, ["title", "platform", "mcu_family", "peripheral", "tags", "updated_at"])
    elif kind == "rules":
        content += _rule_form(filters)
        content += _items_table(items, ["name", "scope", "severity", "applies_to", "updated_at"])
    else:
        content += _example_form(filters)
        content += _items_table(items, ["title", "platform", "framework", "peripheral", "tags", "updated_at"])
    return HTMLResponse(_page(kind.title(), content))


async def _read_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _nav() -> str:
    return """
    <nav>
      <a href="/tasks">Tasks</a>
      <a href="/knowledge">Knowledge</a>
      <a href="/rules">Rules</a>
      <a href="/examples">Examples</a>
    </nav>
    """


def _knowledge_form(filters: dict[str, str]) -> str:
    return f"""
    <section>
      <h1>Knowledge</h1>
      {_filter_form('/knowledge', ['platform', 'mcu_family', 'peripheral', 'tags'], filters)}
      <form method="post" action="/knowledge">
        <label>Title <input name="title" required maxlength="240"></label>
        <div class="grid">
          <label>Domain <input name="domain"></label>
          <label>Platform <input name="platform"></label>
          <label>MCU family <input name="mcu_family"></label>
          <label>Peripheral <input name="peripheral"></label>
          <label>Source <input name="source"></label>
          <label>Quality <input name="quality_level"></label>
        </div>
        <label>Content <textarea name="content" rows="5" required></textarea></label>
        <label>Tags <input name="tags" placeholder="stm32, spi, hal"></label>
        <button type="submit">Create knowledge entry</button>
      </form>
    </section>
    """


def _rule_form(filters: dict[str, str]) -> str:
    return f"""
    <section>
      <h1>Rules</h1>
      {_filter_form('/rules', ['scope', 'severity', 'applies_to'], filters)}
      <form method="post" action="/rules">
        <label>Name <input name="name" required maxlength="240"></label>
        <div class="grid">
          <label>Scope <input name="scope"></label>
          <label>Severity <input name="severity" value="info"></label>
          <label>Applies to <input name="applies_to" placeholder="STM32, HAL"></label>
        </div>
        <label>Rule text <textarea name="rule_text" rows="5" required></textarea></label>
        <button type="submit">Create rule</button>
      </form>
    </section>
    """


def _example_form(filters: dict[str, str]) -> str:
    return f"""
    <section>
      <h1>Examples</h1>
      {_filter_form('/examples', ['platform', 'framework', 'peripheral', 'tags'], filters)}
      <form method="post" action="/examples">
        <label>Title <input name="title" required maxlength="240"></label>
        <div class="grid">
          <label>Platform <input name="platform"></label>
          <label>Framework <input name="framework"></label>
          <label>Language <input name="language"></label>
          <label>Peripheral <input name="peripheral"></label>
        </div>
        <label>Code <textarea name="code" rows="7" required></textarea></label>
        <label>Explanation <textarea name="explanation" rows="3"></textarea></label>
        <label>Known limitations <textarea name="known_limitations" rows="3"></textarea></label>
        <label>Tags <input name="tags" placeholder="nordic, zephyr, spi"></label>
        <button type="submit">Create code example</button>
      </form>
    </section>
    """


def _filter_form(action: str, fields: list[str], filters: dict[str, str]) -> str:
    inputs = "".join(
        f"<label>{escape(field.replace('_', ' ').title())} "
        f"<input name='{escape(field)}' value='{escape(filters.get(field, ''))}'></label>"
        for field in fields
    )
    return f"""
    <form method="get" action="{escape(action)}" class="filters">
      <div class="grid">{inputs}</div>
      <button type="submit">Search</button>
      <a href="{escape(action)}">Clear</a>
    </form>
    """


def _items_table(items: list[dict], columns: list[str]) -> str:
    header = "".join(f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in columns)
    rows = "".join(_item_row(item, columns) for item in items)
    if not rows:
        rows = f"<tr><td colspan='{len(columns)}'>No entries found.</td></tr>"
    return f"""
    <section>
      <h2>Entries</h2>
      <table>
        <thead><tr>{header}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    """


def _item_row(item: dict, columns: list[str]) -> str:
    cells = ""
    for column in columns:
        value = item.get(column)
        if isinstance(value, list):
            value = ", ".join(value)
        cells += f"<td>{escape(str(value or ''))}</td>"
    return f"<tr>{cells}</tr>"


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
        nav {{ display: flex; gap: 16px; margin-bottom: 24px; }}
        section {{ margin-bottom: 32px; }}
        h1, h2 {{ margin: 0 0 16px; }}
        form, table {{ background: #fff; border: 1px solid #d8dee4; border-radius: 8px; }}
        form {{ padding: 16px; margin-bottom: 16px; }}
        .filters {{ background: #eef2f5; }}
        label {{ display: block; margin-bottom: 12px; font-weight: 600; }}
        input, textarea {{ box-sizing: border-box; width: 100%; margin-top: 6px; padding: 10px; border: 1px solid #d0d7de; border-radius: 6px; font: inherit; }}
        button {{ padding: 10px 14px; border: 0; border-radius: 6px; background: #116329; color: #fff; font: inherit; cursor: pointer; }}
        table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #d8dee4; text-align: left; vertical-align: top; }}
        th {{ background: #eef2f5; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
        .error {{ padding: 12px; border: 1px solid #cf222e; border-radius: 6px; background: #ffebe9; color: #cf222e; }}
        a {{ color: #0969da; }}
      </style>
    </head>
    <body>
      <main>{content}</main>
    </body>
    </html>
    """
