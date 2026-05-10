import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.db.repositories import TaskRepository, McpAuditRepository
from app.services.workflow_store import WorkflowStore
import app.api.tasks as tasks_module
from unittest.mock import MagicMock

@pytest.fixture
def client():
    return TestClient(app)

def test_task_workflow_page_renders(client, monkeypatch):
    # Mock dependencies
    mock_task = {
        "id": "test-task-123",
        "title": "Test Task",
        "status": "running",
        "workflow_id": "borg-assimilation"
    }
    
    mock_repo = MagicMock(spec=TaskRepository)
    mock_repo.get_task.return_value = mock_task
    mock_repo.list_events.return_value = []
    
    mock_audit_repo = MagicMock(spec=McpAuditRepository)
    mock_audit_repo.list_logs.return_value = [
        {"created_at": "2024-01-01 10:00:00", "agent_name": "test-agent", "message": "doing stuff"}
    ]
    
    app.dependency_overrides[tasks_module.get_task_repository] = lambda: mock_repo
    app.dependency_overrides[tasks_module.get_mcp_audit_repository] = lambda: mock_audit_repo

    response = client.get("/tasks/test-task-123/workflow")
    app.dependency_overrides.clear()
    
    assert response.status_code == 200
    assert "Workflow: Test Task" in response.text
    assert "Graph" in response.text
    assert "Logs" in response.text
    assert "test-agent" in response.text

def test_task_detail_shows_workflow_link(client, monkeypatch):
    mock_task = {
        "id": "test-task-123",
        "title": "Test Task",
        "status": "running",
        "workflow_id": "borg-assimilation"
    }
    mock_repo = MagicMock(spec=TaskRepository)
    mock_repo.get_task.return_value = mock_task
    mock_repo.list_events.return_value = []
    
    mock_artifact_repo = MagicMock()
    mock_artifact_repo.list_for_task.return_value = []
    mock_project_repo = MagicMock()
    mock_project_repo.list_projects.return_value = []
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: object())
    monkeypatch.setattr(tasks_module.BorgRegistryRepository, "list_items", lambda self: [])
    app.dependency_overrides[tasks_module.get_task_repository] = lambda: mock_repo
    app.dependency_overrides[tasks_module.get_artifact_repository] = lambda: mock_artifact_repo
    app.dependency_overrides[tasks_module.get_project_repository] = lambda: mock_project_repo
    
    response = client.get("/tasks/test-task-123")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "/tasks/test-task-123/workflow" in response.text
    assert "View Workflow" in response.text
