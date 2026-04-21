from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.issues as issues_module
from app.main import create_app
from tests.fakes import FakeSupabaseClient


def test_issues_page_renders_empty_state(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": [], "projects": []})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/issues")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Issue tracker" in response.text
    assert "New issue" in response.text


def test_issues_page_lists_issues_sorted_by_recent(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "issues": [
                {"id": "i-old", "title": "Old Bug", "status": "open", "priority": "low", "project_id": "p1", "updated_at": "2026-04-10T10:00:00+00:00"},
                {"id": "i-new", "title": "New Bug", "status": "open", "priority": "high", "project_id": "p1", "updated_at": "2026-04-12T10:00:00+00:00"},
            ],
            "projects": [{"id": "p1", "name": "Project Alpha", "active": True}],
        }
    )
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/issues")

    assert response.status_code == 200
    assert "New Bug" in response.text
    assert "Old Bug" in response.text
    assert response.text.index("New Bug") < response.text.index("Old Bug")


def test_issues_page_filters_by_project(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "issues": [
                {"id": "i1", "title": "Bug A", "status": "open", "priority": "medium", "project_id": "p1", "updated_at": "2026-04-12T10:00:00+00:00"},
                {"id": "i2", "title": "Bug B", "status": "open", "priority": "medium", "project_id": "p2", "updated_at": "2026-04-11T10:00:00+00:00"},
            ],
            "projects": [
                {"id": "p1", "name": "Project Alpha", "active": True},
                {"id": "p2", "name": "Project Beta", "active": True},
            ],
        }
    )
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/issues?project_id=p1")

    assert response.status_code == 200
    assert "Bug A" in response.text
    assert "Bug B" not in response.text


def test_create_issue_via_form(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": [], "projects": [{"id": "p1", "name": "Project Alpha", "active": True}]})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post(
        "/issues",
        data={"title": "New Issue", "description": "Something is broken", "project_id": "p1", "priority": "high"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(fake_client.tables["issues"]) == 1
    assert fake_client.tables["issues"][0]["title"] == "New Issue"
    assert fake_client.tables["issues"][0]["priority"] == "high"
    assert fake_client.tables["issues"][0]["project_id"] == "p1"


def test_update_issue_status_via_form(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "issues": [{"id": "i1", "title": "Bug", "status": "open", "priority": "medium", "project_id": "p1"}],
            "projects": [],
        }
    )
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post(
        "/issues/i1/status",
        data={"status": "in_progress"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert fake_client.tables["issues"][0]["status"] == "in_progress"


def test_issues_navigation_link_visible(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": [], "projects": []})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/issues")

    assert response.status_code == 200
    assert 'href="/issues"' in response.text
    assert "Issues" in response.text


def test_issues_api_list(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "issues": [
                {"id": "i1", "title": "Bug", "status": "open", "priority": "medium", "project_id": "p1", "updated_at": "2026-04-12T10:00:00+00:00"},
            ],
        }
    )
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/api/issues")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Bug"


def test_issues_api_create(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": []})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post("/api/issues", json={"title": "API Issue", "description": "Test", "priority": "critical"})

    assert response.status_code == 201
    assert response.json()["title"] == "API Issue"
    assert len(fake_client.tables["issues"]) == 1


def test_issues_page_shows_checkboxes(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "issues": [
                {"id": "i1", "title": "Bug A", "status": "open", "priority": "medium", "project_id": "p1", "updated_at": "2026-04-12T10:00:00+00:00"},
            ],
            "projects": [{"id": "p1", "name": "Project Alpha", "active": True}],
        }
    )
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/issues")

    assert response.status_code == 200
    assert 'name="issue_ids"' in response.text
    assert 'value="i1"' in response.text
    assert 'class="issue-check"' in response.text
    assert 'id="select-all"' in response.text


def test_issues_page_shows_workflow_dropdown(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": [], "projects": []})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/issues")

    assert response.status_code == 200
    assert 'name="workflow_id"' in response.text
    assert "Select workflow" in response.text
    assert "Start workflow" in response.text


def test_start_workflow_creates_tasks(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "issues": [
                {"id": "i1", "title": "Bug A", "status": "open", "priority": "high", "project_id": "p1", "description": "Desc A"},
                {"id": "i2", "title": "Bug B", "status": "open", "priority": "medium", "project_id": "p1", "description": "Desc B"},
            ],
            "projects": [{"id": "p1", "name": "Project Alpha", "active": True, "project_directory": "/tmp/proj"}],
            "tasks": [],
            "task_events": [],
        }
    )
    started_task_ids: list[str] = []
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    monkeypatch.setattr(issues_module, "_schedule_task_processing", lambda _bg, _settings, task_id: started_task_ids.append(task_id))
    client = TestClient(create_app())

    response = client.post(
        "/issues/start-workflow",
        data={"workflow_id": "borg-nanoprobe-repair", "issue_ids": ["i1", "i2"]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(fake_client.tables["tasks"]) == 2
    assert fake_client.tables["tasks"][0]["workflow_id"] == "borg-nanoprobe-repair"
    assert "Bug A" in fake_client.tables["tasks"][0]["title"]
    assert "Bug B" in fake_client.tables["tasks"][1]["title"]
    assert fake_client.tables["issues"][0]["status"] == "in_progress"
    assert fake_client.tables["issues"][1]["status"] == "in_progress"
    assert len(fake_client.tables["task_events"]) == 4  # 2x task_created + 2x workflow_selected
    workflow_events = [e for e in fake_client.tables["task_events"] if e["event_type"] == "workflow_selected"]
    assert len(workflow_events) == 2
    assert workflow_events[0]["payload"]["issue_id"] == "i1"
    assert workflow_events[1]["payload"]["issue_id"] == "i2"
    assert started_task_ids == [fake_client.tables["tasks"][0]["id"], fake_client.tables["tasks"][1]["id"]]


def test_start_workflow_requires_workflow_id(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": [], "projects": [], "tasks": [], "task_events": []})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post(
        "/issues/start-workflow",
        data={"issue_ids": ["i1"]},
        follow_redirects=False,
    )

    assert response.status_code == 400


def test_start_workflow_requires_issue_selection(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"issues": [], "projects": [], "tasks": [], "task_events": []})
    monkeypatch.setattr(issues_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post(
        "/issues/start-workflow",
        data={"workflow_id": "borg-nanoprobe-repair"},
        follow_redirects=False,
    )

    assert response.status_code == 400
