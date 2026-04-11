from __future__ import annotations

from typing import Any

from app.db.supabase_client import SupabaseRestClient, SupabaseRestError


def search_table(
    client: SupabaseRestClient,
    table: str,
    arguments: dict[str, Any],
    *,
    text_columns: tuple[str, ...],
    filter_columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    limit = _limit(arguments)
    query: dict[str, str] = {"select": "*", "limit": str(limit), "order": "updated_at.desc"}

    for column in filter_columns:
        value = _clean(arguments.get(column))
        if not value:
            continue
        if column in {"tags", "applies_to"}:
            query[column] = f"cs.{{{value}}}"
        else:
            query[column] = f"ilike.*{value}*"

    rows = client.request("GET", table, query=query)
    text_query = _clean(arguments.get("query"))
    if text_query:
        rows = [
            row for row in rows
            if any(text_query.lower() in str(row.get(column, "")).lower() for column in text_columns)
        ]
    return rows[:limit]


def get_item(client: SupabaseRestClient, table: str, arguments: dict[str, Any]) -> dict[str, Any]:
    item_id = _required(arguments, "id")
    rows = client.request("GET", table, query={"select": "*", "id": f"eq.{item_id}", "limit": "1"})
    if not rows:
        raise ValueError(f"No item found in {table} for id {item_id}")
    return rows[0]


def project_search(client: SupabaseRestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    shared = {
        "query": arguments.get("query"),
        "platform": arguments.get("platform"),
        "peripheral": arguments.get("peripheral"),
        "limit": arguments.get("limit", 10),
    }
    knowledge = search_table(
        client,
        "knowledge_entries",
        shared,
        text_columns=("title", "content", "source"),
        filter_columns=("platform", "peripheral"),
    )
    rules = search_table(
        client,
        "rules",
        {"query": arguments.get("query"), "limit": arguments.get("limit", 10)},
        text_columns=("name", "rule_text", "scope"),
        filter_columns=("scope", "severity", "applies_to"),
    )
    examples = search_table(
        client,
        "code_examples",
        shared,
        text_columns=("title", "code", "explanation"),
        filter_columns=("platform", "peripheral"),
    )
    tasks = client.request(
        "GET",
        "tasks",
        query={"select": "*", "limit": str(_limit(arguments)), "order": "updated_at.desc"},
    )
    text_query = _clean(arguments.get("query"))
    if text_query:
        tasks = [
            task for task in tasks
            if text_query.lower() in f"{task.get('title', '')} {task.get('description', '')} {task.get('topic', '')}".lower()
        ]
    return {"knowledge": knowledge, "rules": rules, "examples": examples, "tasks": tasks}


def optional_table_list(client: SupabaseRestClient, table: str) -> list[dict[str, Any]]:
    try:
        return client.request("GET", table, query={"select": "*", "order": "name.asc"})
    except SupabaseRestError as exc:
        if exc.status_code == 404:
            return []
        raise


def _required(arguments: dict[str, Any], key: str) -> str:
    value = _clean(arguments.get(key))
    if not value:
        raise ValueError(f"Missing required argument: {key}")
    return value


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _limit(arguments: dict[str, Any]) -> int:
    raw = arguments.get("limit", 10)
    try:
        return max(1, min(int(raw), 50))
    except (TypeError, ValueError):
        return 10
