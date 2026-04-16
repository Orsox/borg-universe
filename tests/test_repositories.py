from __future__ import annotations

from app.db.repositories import ContentRepository, McpAuditRepository, ProjectRepository, TaskRepository
from app.db.supabase_client import SupabaseRestError
from app.models.knowledge import KnowledgeEntryCreate
from app.models.tasks import TaskCreate
from tests.fakes import FakeSupabaseClient


def test_task_repository_creates_task_and_event() -> None:
    client = FakeSupabaseClient({"tasks": [], "task_events": []})
    repo = TaskRepository(client)  # type: ignore[arg-type]

    task = repo.create_task(
        TaskCreate(
            title="STM32 SPI",
            topic="SPI",
            workspace_metadata={"worktree_path": "/tmp/worktrees/impl/t1", "branch_name": "impl/t1"},
        )
    )

    assert task["title"] == "STM32 SPI"
    assert client.tables["task_events"][0]["event_type"] == "task_created"
    assert task["workspace_metadata"]["branch_name"] == "impl/t1"
    assert client.tables["task_events"][0]["payload"]["workspace_metadata"]["worktree_path"] == "/tmp/worktrees/impl/t1"


def test_task_repository_keeps_task_when_event_insert_fails() -> None:
    class EventFailingClient(FakeSupabaseClient):
        def request(self, method: str, path: str, **kwargs):  # type: ignore[override]
            if method.upper() == "POST" and path == "task_events":
                raise RuntimeError("task_events unavailable")
            return super().request(method, path, **kwargs)

    client = EventFailingClient({"tasks": [], "task_events": []})
    repo = TaskRepository(client)  # type: ignore[arg-type]

    task = repo.create_task(TaskCreate(title="Persist task even without events"))

    assert task["title"] == "Persist task even without events"
    assert client.tables["tasks"][0]["title"] == "Persist task even without events"
    assert client.tables["task_events"] == []


def test_task_repository_omits_empty_workspace_metadata_from_insert() -> None:
    client = FakeSupabaseClient({"tasks": [], "task_events": []})
    repo = TaskRepository(client)  # type: ignore[arg-type]

    repo.create_task(TaskCreate(title="No workspace metadata body"))

    create_call = next(call for call in client.calls if call["method"] == "POST" and call["path"] == "tasks")
    assert "workspace_metadata" not in create_call["body"]


def test_task_repository_retries_when_workspace_metadata_is_unknown_to_postgrest() -> None:
    class WorkspaceMetadataCacheClient(FakeSupabaseClient):
        def request(self, method: str, path: str, **kwargs):  # type: ignore[override]
            body = kwargs.get("body") or {}
            if method.upper() == "POST" and path == "tasks" and "workspace_metadata" in body:
                raise SupabaseRestError(400, '{"code":"PGRST204","message":"Could not find the workspace_metadata column"}')
            return super().request(method, path, **kwargs)

    client = WorkspaceMetadataCacheClient({"tasks": [], "task_events": []})
    repo = TaskRepository(client)  # type: ignore[arg-type]

    task = repo.create_task(
        TaskCreate(title="Retry without workspace metadata", workspace_metadata={"branch_name": "impl/t1"})
    )

    assert task["title"] == "Retry without workspace metadata"
    task_posts = [call for call in client.calls if call["method"] == "POST" and call["path"] == "tasks"]
    assert len(task_posts) == 2
    assert "workspace_metadata" in task_posts[0]["body"]
    assert "workspace_metadata" not in task_posts[1]["body"]


def test_task_repository_update_status_records_transition() -> None:
    client = FakeSupabaseClient(
        {"tasks": [{"id": "t1", "title": "Task", "status": "draft"}], "task_events": []}
    )
    repo = TaskRepository(client)  # type: ignore[arg-type]

    updated = repo.update_status("t1", "queued")

    assert updated is not None
    assert updated["status"] == "queued"
    assert client.tables["task_events"][0]["payload"] == {"from": "draft", "to": "queued"}


def test_project_repository_lists_active_projects() -> None:
    client = FakeSupabaseClient(
        {
            "projects": [
                {"id": "example-1", "name": "Example 1", "active": True},
                {"id": "example-2", "name": "Example 2", "active": True},
                {"id": "archiv", "name": "Archiv", "active": False},
            ]
        }
    )
    repo = ProjectRepository(client)  # type: ignore[arg-type]

    rows = repo.list_projects()

    assert [row["id"] for row in rows] == ["example-1", "example-2"]
    assert client.calls[-1]["query"]["active"] == "eq.true"


def test_content_repository_maps_tag_filter_to_contains_query() -> None:
    client = FakeSupabaseClient(
        {
            "knowledge_entries": [
                {"id": "k1", "title": "SPI", "content": "x", "tags": ["stm32", "spi"]},
                {"id": "k2", "title": "UART", "content": "x", "tags": ["uart"]},
            ]
        }
    )
    repo = ContentRepository(client, "knowledge_entries")  # type: ignore[arg-type]

    rows = repo.list_items({"tags": "spi"})

    assert [row["id"] for row in rows] == ["k1"]
    assert client.calls[-1]["query"]["tags"] == "cs.{spi}"


def test_content_repository_create_uses_payload_model() -> None:
    client = FakeSupabaseClient({"knowledge_entries": []})
    repo = ContentRepository(client, "knowledge_entries")  # type: ignore[arg-type]

    created = repo.create_item(KnowledgeEntryCreate(title="Entry", content="Body", tags=["phase9"]))

    assert created["title"] == "Entry"
    assert client.tables["knowledge_entries"][0]["tags"] == ["phase9"]


def test_mcp_audit_repository_filters_success_and_task_id() -> None:
    client = FakeSupabaseClient({"mcp_access_logs": []})
    repo = McpAuditRepository(client)  # type: ignore[arg-type]

    repo.list_logs({"task_id": "t1", "success": "false", "tool_name": "project"})

    query = client.calls[-1]["query"]
    assert query["task_id"] == "eq.t1"
    assert query["success"] == "eq.false"
    assert query["tool_name"] == "ilike.*project*"
