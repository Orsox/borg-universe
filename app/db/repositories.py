from __future__ import annotations

from typing import Any

from app.db.supabase_client import SupabaseRestClient
from app.models.borg import BorgSkill, BorgUnit
from app.models.knowledge import CodeExampleCreate, KnowledgeEntryCreate, RuleCreate
from app.models.projects import ProjectCreate
from app.models.tasks import TaskCreate, TaskStatus


class ProjectRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def list_projects(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        query: dict[str, str] = {"select": "*", "order": "name.asc"}
        if not include_inactive:
            query["active"] = "eq.true"
        return self.client.request("GET", "projects", query=query)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            "projects",
            query={"select": "*", "id": f"eq.{project_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def create_project(self, project: ProjectCreate) -> dict[str, Any]:
        return self.client.request(
            "POST",
            "projects",
            query={"select": "*"},
            body=project.model_dump(exclude_none=True),
            prefer="return=representation",
        )[0]

    def delete_project(self, project_id: str) -> bool:
        self.client.request(
            "DELETE",
            "projects",
            query={"id": f"eq.{project_id}"},
            prefer="return=minimal",
        )
        return True


class ProjectSpecRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "project_specs",
            query={"select": "*", "project_id": f"eq.{project_id}", "order": "spec_path.asc"},
        )

    def upsert_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        rows = self.client.request(
            "POST",
            "project_specs",
            query={"select": "*", "on_conflict": "project_id,spec_path"},
            body=spec,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]

    def upsert_specs(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not specs:
            return []
        return [
            self.upsert_spec(spec)
            for spec in specs
        ]

    def delete_for_project(self, project_id: str) -> None:
        self.client.request(
            "DELETE",
            "project_specs",
            query={"project_id": f"eq.{project_id}"},
            prefer="return=minimal",
        )


class TaskRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def list_tasks(self) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "tasks",
            query={"select": "*", "order": "updated_at.desc,created_at.desc"},
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            "tasks",
            query={"select": "*", "id": f"eq.{task_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def list_by_status(self, status: TaskStatus, limit: int = 10) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "tasks",
            query={
                "select": "*",
                "status": f"eq.{status}",
                "order": "created_at.asc",
                "limit": str(limit),
            },
        )

    def list_stale_running(self, updated_before_iso: str, limit: int = 10) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "tasks",
            query={
                "select": "*",
                "status": "eq.running",
                "updated_at": f"lt.{updated_before_iso}",
                "order": "updated_at.asc",
                "limit": str(limit),
            },
        )

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "tasks",
            query={"select": "*", "project_id": f"eq.{project_id}", "order": "created_at.asc"},
        )

    def list_child_implementation_tasks(self, parent_task_id: str) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "tasks",
            query={
                "select": "*",
                "assigned_agent": "eq.borg-implementation-drone",
                "description": f"ilike.*Parent task: {parent_task_id}*",
                "order": "created_at.asc",
            },
        )

    def delete_for_project(self, project_id: str) -> None:
        self.client.request(
            "DELETE",
            "tasks",
            query={"project_id": f"eq.{project_id}"},
            prefer="return=minimal",
        )

    def create_task(self, task: TaskCreate, initial_status: TaskStatus = "queued") -> dict[str, Any]:
        body = task.model_dump(exclude_none=True)
        body["status"] = initial_status
        row = self.client.request(
            "POST",
            "tasks",
            query={"select": "*"},
            body=body,
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

    def update_fields(self, task_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        previous = self.get_task(task_id)
        if not previous or not fields:
            return previous

        rows = self.client.request(
            "PATCH",
            "tasks",
            query={"select": "*", "id": f"eq.{task_id}"},
            body=fields,
            prefer="return=representation",
        )
        return rows[0] if rows else None

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


class ArtifactRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def create_artifact(
        self,
        *,
        task_id: str,
        artifact_type: str,
        path_or_storage_key: str,
        checksum: str | None = None,
    ) -> dict[str, Any]:
        return self.client.request(
            "POST",
            "artifacts",
            query={"select": "*"},
            body={
                "task_id": task_id,
                "artifact_type": artifact_type,
                "path_or_storage_key": path_or_storage_key,
                "checksum": checksum,
            },
            prefer="return=representation",
        )[0]

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            "artifacts",
            query={"select": "*", "task_id": f"eq.{task_id}", "order": "created_at.desc"},
        )


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


class ProjectRegistryBindingRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client
        self.table = "project_registry_bindings"

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return self.client.request(
            "GET",
            self.table,
            query={"select": "*", "project_id": f"eq.{project_id}"},
        )

    def bind_units(self, project_id: str, units: list[dict[str, str]]) -> list[dict[str, Any]]:
        if not units:
            return []

        body = [
            {"project_id": project_id, "unit_name": u["name"], "unit_type": u["type"]}
            for u in units
        ]

        return self.client.request(
            "POST",
            self.table,
            query={"select": "*", "on_conflict": "project_id,unit_name,unit_type"},
            body=body,
            prefer="resolution=merge-duplicates,return=representation",
        )

    def unbind_all(self, project_id: str) -> bool:
        self.client.request(
            "DELETE",
            self.table,
            query={"project_id": f"eq.{project_id}"},
            prefer="return=minimal",
        )
        return True


class McpAuditRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self.client = client

    def list_logs(self, filters: dict[str, str | None], limit: int = 100) -> list[dict[str, Any]]:
        query: dict[str, str] = {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        for key in ("agent_name", "skill_name", "tool_name", "task_id", "project_id"):
            value = filters.get(key)
            if value:
                query[key] = f"ilike.*{value}*" if key != "task_id" else f"eq.{value}"
        success = filters.get("success")
        if success in {"true", "false"}:
            query["success"] = f"eq.{success}"
        return self.client.request("GET", "mcp_access_logs", query=query)
