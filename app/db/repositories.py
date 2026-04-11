from __future__ import annotations

from typing import Any

from app.db.supabase_client import SupabaseRestClient
from app.models.borg import BorgSkill, BorgUnit
from app.models.knowledge import CodeExampleCreate, KnowledgeEntryCreate, RuleCreate
from app.models.tasks import TaskCreate, TaskStatus


class TaskRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def list_tasks(self) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "tasks",
            query={"select": "*", "order": "created_at.desc"},
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            "tasks",
            query={"select": "*", "id": f"eq.{task_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def create_task(self, task: TaskCreate) -> dict[str, Any]:
        row = self.client.request(
            "POST",
            "tasks",
            query={"select": "*"},
            body=task.model_dump(exclude_none=True),
            prefer="return=representation",
        )[0]
        self.add_event(
            row["id"],
            "task_created",
            "Task created.",
            {"status": row["status"]},
        )
        return row

    def update_status(self, task_id: str, status: TaskStatus) -> dict[str, Any] | None:
        previous = self.get_task(task_id)
        if not previous:
            return None

        rows = self.client.request(
            "PATCH",
            "tasks",
            query={"select": "*", "id": f"eq.{task_id}"},
            body={"status": status},
            prefer="return=representation",
        )
        if not rows:
            return None

        updated = rows[0]
        self.add_event(
            task_id,
            "status_changed",
            f"Status changed from {previous['status']} to {updated['status']}.",
            {"from": previous["status"], "to": updated["status"]},
        )
        return updated

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "task_events",
            query={"select": "*", "task_id": f"eq.{task_id}", "order": "created_at.asc"},
        )

    def add_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.client.request(
            "POST",
            "task_events",
            query={"select": "*"},
            body={
                "task_id": task_id,
                "event_type": event_type,
                "message": message,
                "payload": payload or {},
            },
            prefer="return=representation",
        )[0]


class ContentRepository:
    def __init__(self, client: SupabaseRestClient, table: str) -> None:
        self.client = client
        self.table = table

    def list_items(self, filters: dict[str, str | None]) -> list[dict[str, Any]]:
        query: dict[str, str] = {"select": "*", "order": "updated_at.desc"}
        for key, value in filters.items():
            if value:
                if key in {"tags", "applies_to"}:
                    query[key] = f"cs.{{{value}}}"
                else:
                    query[key] = f"ilike.*{value}*"
        return self.client.request("GET", self.table, query=query)

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            self.table,
            query={"select": "*", "id": f"eq.{item_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def create_item(self, payload: KnowledgeEntryCreate | RuleCreate | CodeExampleCreate) -> dict[str, Any]:
        return self.client.request(
            "POST",
            self.table,
            query={"select": "*"},
            body=payload.model_dump(exclude_none=True),
            prefer="return=representation",
        )[0]

    def update_item(
        self,
        item_id: str,
        payload: KnowledgeEntryCreate | RuleCreate | CodeExampleCreate,
    ) -> dict[str, Any] | None:
        rows = self.client.request(
            "PATCH",
            self.table,
            query={"select": "*", "id": f"eq.{item_id}"},
            body=payload.model_dump(exclude_none=True),
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def delete_item(self, item_id: str) -> bool:
        self.client.request(
            "DELETE",
            self.table,
            query={"id": f"eq.{item_id}"},
            prefer="return=minimal",
        )
        return True


class BorgRegistryRepository:
    def __init__(self, client: SupabaseRestClient, table: str) -> None:
        self.client = client
        self.table = table

    def list_items(self) -> list[dict[str, Any]]:
        return self.client.request("GET", self.table, query={"select": "*", "order": "name.asc"})

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            self.table,
            query={"select": "*", "name": f"eq.{name}", "limit": "1"},
        )
        return rows[0] if rows else None

    def sync(self, units: list[BorgUnit | BorgSkill]) -> list[dict[str, Any]]:
        if not units:
            return []
        body = [unit.model_dump(exclude_none=True) for unit in units]
        return self.client.request(
            "POST",
            self.table,
            query={"select": "*", "on_conflict": "name"},
            body=body,
            prefer="resolution=merge-duplicates,return=representation",
        )

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any] | None:
        rows = self.client.request(
            "PATCH",
            self.table,
            query={"select": "*", "name": f"eq.{name}"},
            body={"enabled": enabled},
            prefer="return=representation",
        )
        return rows[0] if rows else None
