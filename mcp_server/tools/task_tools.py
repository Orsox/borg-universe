from __future__ import annotations

from typing import Any

from app.db.supabase_client import SupabaseRestClient


def get_task(client: SupabaseRestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = _required(arguments, "id")
    rows = client.request("GET", "tasks", query={"select": "*", "id": f"eq.{task_id}", "limit": "1"})
    if not rows:
        raise ValueError(f"Task not found: {task_id}")
    events = client.request(
        "GET",
        "task_events",
        query={"select": "*", "task_id": f"eq.{task_id}", "order": "created_at.asc"},
    )
    return {"task": rows[0], "events": events}


def add_event(client: SupabaseRestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = _required(arguments, "task_id")
    event_type = _required(arguments, "event_type")
    message = _required(arguments, "message")
    payload = arguments.get("payload") or {}
    return client.request(
        "POST",
        "task_events",
        query={"select": "*"},
        body={"task_id": task_id, "event_type": event_type, "message": message, "payload": payload},
        prefer="return=representation",
    )[0]


def request_input(client: SupabaseRestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = _required(arguments, "task_id")
    message = _required(arguments, "message")
    client.request(
        "PATCH",
        "tasks",
        query={"id": f"eq.{task_id}", "select": "*"},
        body={"status": "needs_input"},
        prefer="return=representation",
    )
    return add_event(
        client,
        {
            "task_id": task_id,
            "event_type": "input_requested",
            "message": message,
            "payload": arguments.get("payload") or {},
        },
    )


def create_artifact_event(client: SupabaseRestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = _required(arguments, "task_id")
    artifact_type = _required(arguments, "artifact_type")
    path_or_storage_key = _required(arguments, "path_or_storage_key")
    return add_event(
        client,
        {
            "task_id": task_id,
            "event_type": "artifact_created",
            "message": f"Artifact recorded: {artifact_type}",
            "payload": {
                "artifact_type": artifact_type,
                "path_or_storage_key": path_or_storage_key,
                "checksum": arguments.get("checksum"),
            },
        },
    )


def _required(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"Missing required argument: {key}")
    return str(value).strip()
