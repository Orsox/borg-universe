from __future__ import annotations

from app.db.repositories import ContentRepository, McpAuditRepository, ProjectRepository, TaskRepository
from app.models.knowledge import KnowledgeEntryCreate
from app.models.tasks import TaskCreate
from tests.fakes import FakeSupabaseClient


def test_task_repository_creates_task_and_event() -> None:
    client = FakeSupabaseClient({"tasks": [], "task_events": []})
    repo = TaskRepository(client)  # type: ignore[arg-type]

    task = repo.create_task(TaskCreate(title="STM32 SPI", topic="SPI"))

    assert task["title"] == "STM32 SPI"
    assert client.tables["task_events"][0]["event_type"] == "task_created"


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
