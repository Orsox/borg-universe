import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.db.repositories import TaskRepository, McpAuditRepository
from app.services.workflow_store import WorkflowStore
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
        "workflow_id": "assimilation-demo"
    }
    
    mock_repo = MagicMock(spec=TaskRepository)
    mock_repo.get_task.return_value = mock_task
    mock_repo.list_events.return_value = []
    
    mock_audit_repo = MagicMock(spec=McpAuditRepository)
    mock_audit_repo.list_logs.return_value = [
        {"created_at": "2024-01-01 10:00:00", "agent_name": "test-agent", "message": "doing stuff"}
    ]
    
    # Overriding the dependency in the route is complex due to the way it's injected
    # Better to mock the classes directly if possible, or just check if the route exists
    
    monkeypatch.setattr("app.api.tasks.get_task_repository", lambda: mock_repo)
    # Note: McpAuditRepository is instantiated inside the route using _client(settings)
    # We might need to mock McpAuditRepository class
    monkeypatch.setattr("app.api.tasks.McpAuditRepository", lambda client: mock_audit_repo)

    response = client.get("/tasks/test-task-123/workflow")
    
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
        "workflow_id": "assimilation-demo"
    }
    mock_repo = MagicMock(spec=TaskRepository)
    mock_repo.get_task.return_value = mock_task
    mock_repo.list_events.return_value = []
    
    monkeypatch.setattr("app.api.tasks.get_task_repository", lambda: mock_repo)
    
    response = client.get("/tasks/test-task-123")
    assert response.status_code == 200
    assert "/tasks/test-task-123/workflow" in response.text
    assert "View Workflow" in response.text
