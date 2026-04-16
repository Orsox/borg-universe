from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
import app.main as main_module
import app.api.tasks as tasks_module
from app.services.orchestration_settings_store import OrchestrationSettings
from app.main import create_app
from tests.fakes import FakeSupabaseClient


def test_health_endpoint_reports_service() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_renders_borg_homepage_template() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Borg Universe Command Node" in response.text
    assert "Local control node for tasks, knowledge, agents, skills, and auditable MCP access." in response.text
    assert 'href="/workflows"' in response.text
    assert "YAML flow and node boxes" in response.text
    assert "New task" not in response.text
    assert "New project" in response.text
    assert "Task telemetry" in response.text


def test_root_shows_task_telemetry_counts(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "projects": [{"id": "example-1", "name": "Example 1", "active": True}],
            "tasks": [
                {"id": "t1", "title": "Done", "status": "done"},
                {"id": "t2", "title": "Review", "status": "review_required"},
                {"id": "t3", "title": "Run", "status": "running"},
                {"id": "t4", "title": "Queued", "status": "queued"},
            ],
        }
    )
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Processed" in response.text
    assert ">2<" in response.text or "<dd>2</dd>" in response.text
    assert "Active" in response.text
    assert ">1<" in response.text or "<dd>1</dd>" in response.text


def test_root_shows_review_required_tasks(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "projects": [{"id": "example-1", "name": "Example 1", "active": True}],
            "tasks": [
                {"id": "t1", "title": "Review me", "status": "review_required", "description": "Needs review", "updated_at": "2026-04-12T10:00:00+00:00"},
                {"id": "t2", "title": "Done", "status": "done", "description": "Finished", "updated_at": "2026-04-12T09:00:00+00:00"},
            ],
        }
    )
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Review required" in response.text
    assert "/tasks/t1/review" in response.text
    assert "Review me" in response.text


def test_root_shows_needs_input_tasks_before_review_queue(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "projects": [{"id": "firststart", "name": "First Start", "active": True}],
            "tasks": [
                {
                    "id": "input-new",
                    "title": "Second input",
                    "status": "needs_input",
                    "description": "Needs later clarification",
                    "project_id": "firststart",
                    "local_path": r"D:\Workbench\firststart",
                    "updated_at": "2026-04-12T11:00:00+00:00",
                },
                {
                    "id": "input-old",
                    "title": "First input",
                    "status": "needs_input",
                    "description": "Needs first clarification",
                    "project_id": "firststart",
                    "local_path": r"D:\Workbench\firststart",
                    "updated_at": "2026-04-12T10:00:00+00:00",
                },
                {
                    "id": "review-1",
                    "title": "Review me",
                    "status": "review_required",
                    "description": "Needs review",
                    "updated_at": "2026-04-12T12:00:00+00:00",
                },
            ],
        }
    )
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Input required" in response.text
    assert "First input" in response.text
    assert "Second input" in response.text
    assert "/tasks/input-old/review" in response.text
    assert response.text.index("First input") < response.text.index("Second input")
    assert response.text.index("Input required") < response.text.index("Review required")
    assert 'window.location.reload()' in response.text


def test_tasks_page_orders_most_recent_tasks_first(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [
                {"id": "old", "title": "Older Task", "status": "draft", "updated_at": "2026-04-11T10:00:00+00:00"},
                {"id": "new", "title": "Newer Task", "status": "queued", "updated_at": "2026-04-12T10:00:00+00:00"},
            ],
            "projects": [],
        }
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.text.index("Newer Task") < response.text.index("Older Task")


def test_command_node_creates_python_project(monkeypatch) -> None:
    fake_client = FakeSupabaseClient({"projects": []})
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    page = client.get("/projects/new")

    assert page.status_code == 200
    assert "Project setup" in page.text
    assert 'value="python"' in page.text
    assert 'name="project_directory"' in page.text
    assert 'name="pycharm_mcp_enabled"' in page.text
    assert 'name="pycharm_mcp_sse_url"' in page.text
    assert 'name="pycharm_mcp_stream_url"' in page.text

    response = client.post(
        "/projects",
        data={
            "name": "Automation Tools",
            "id": "",
            "project_type": "python",
            "description": "Python runtime and tooling project.",
            "project_directory": r"D:\Workbench\firststart",
            "pycharm_mcp_enabled": "on",
            "pycharm_mcp_sse_url": "http://127.0.0.1:64769/sse",
            "pycharm_mcp_stream_url": "http://127.0.0.1:64769/stream",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert fake_client.tables["projects"][0]["id"] == "automation-tools"
    assert fake_client.tables["projects"][0]["project_type"] == "python"
    assert fake_client.tables["projects"][0]["name"] == "Automation Tools"
    assert fake_client.tables["projects"][0]["project_directory"] == r"D:\Workbench\firststart"
    assert fake_client.tables["projects"][0]["pycharm_mcp_enabled"] is True
    assert fake_client.tables["projects"][0]["pycharm_mcp_sse_url"] == "http://127.0.0.1:64769/sse"
    assert fake_client.tables["projects"][0]["pycharm_mcp_stream_url"] == "http://127.0.0.1:64769/stream"
    assert response.headers["location"] == "/projects/new"


def test_projects_overview_lists_projects_with_delete_actions(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "projects": [
                {
                    "id": "example-1",
                    "name": "Example 1",
                    "description": "First project",
                    "project_type": "python",
                    "project_directory": r"D:\Workbench\firststart",
                    "pycharm_mcp_enabled": True,
                    "pycharm_mcp_stream_url": "http://127.0.0.1:64769/stream",
                    "active": True,
                },
                {
                    "id": "example-2",
                    "name": "Example 2",
                    "description": "Second project",
                    "project_type": "stm",
                    "project_directory": r"D:\Workbench\second",
                    "pycharm_mcp_enabled": False,
                    "active": False,
                },
            ]
        }
    )
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    page = client.get("/projects")

    assert page.status_code == 200
    assert "Project Overview" in page.text
    assert "Example 1" in page.text
    assert "Example 2" in page.text
    assert 'action="/projects/example-1/delete"' in page.text
    assert 'action="/projects/example-2/delete"' in page.text
    assert 'href="/projects/new"' in page.text
    assert 'href="/"' in page.text


def test_projects_delete_endpoint_removes_project(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "projects": [
                {
                    "id": "example-1",
                    "name": "Example 1",
                    "description": "First project",
                    "project_type": "python",
                    "project_directory": r"D:\Workbench\firststart",
                    "pycharm_mcp_enabled": True,
                    "active": True,
                }
            ]
        }
    )
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post("/projects/example-1/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/projects"
    assert fake_client.tables["projects"] == []


def test_projects_delete_endpoint_removes_project_related_entries(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "projects": [
                {
                    "id": "example-1",
                    "name": "Example 1",
                    "description": "First project",
                    "project_type": "python",
                    "project_directory": r"D:\Workbench\firststart",
                    "pycharm_mcp_enabled": True,
                    "active": True,
                }
            ],
            "tasks": [
                {"id": "task-1", "project_id": "example-1", "title": "Task 1", "status": "done"},
                {"id": "task-2", "project_id": "example-1", "title": "Task 2", "status": "queued"},
                {"id": "task-other", "project_id": "example-2", "title": "Other Task", "status": "draft"},
            ],
            "task_events": [
                {"id": "ev-1", "task_id": "task-1", "event_type": "note", "message": "A", "payload": {}},
                {"id": "ev-2", "task_id": "task-2", "event_type": "note", "message": "B", "payload": {}},
                {"id": "ev-other", "task_id": "task-other", "event_type": "note", "message": "C", "payload": {}},
            ],
            "artifacts": [
                {"id": "ar-1", "task_id": "task-1", "artifact_type": "report", "path_or_storage_key": "a"},
                {"id": "ar-2", "task_id": "task-2", "artifact_type": "report", "path_or_storage_key": "b"},
                {"id": "ar-other", "task_id": "task-other", "artifact_type": "report", "path_or_storage_key": "c"},
            ],
            "project_specs": [
                {"id": "spec-1", "project_id": "example-1", "spec_path": "borg-cube.md", "title": "Cube", "content": "# Cube"},
                {"id": "spec-other", "project_id": "example-2", "spec_path": "borg-cube.md", "title": "Other", "content": "# Other"},
            ],
            "mcp_access_logs": [
                {"id": "log-1", "project_id": "example-1", "tool_name": "project.search", "result_count": 1},
                {"id": "log-other", "project_id": "example-2", "tool_name": "project.search", "result_count": 1},
            ],
        }
    )
    monkeypatch.setattr(main_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post("/projects/example-1/delete", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/projects"
    assert fake_client.tables["projects"] == []
    assert [row["id"] for row in fake_client.tables["tasks"]] == ["task-other"]
    assert [row["id"] for row in fake_client.tables["task_events"]] == ["ev-other"]
    assert [row["id"] for row in fake_client.tables["artifacts"]] == ["ar-other"]
    assert [row["id"] for row in fake_client.tables["project_specs"]] == ["spec-other"]
    assert [row["id"] for row in fake_client.tables["mcp_access_logs"]] == ["log-other"]


def test_orchestration_page_saves_agent_selection(tmp_path) -> None:
    settings = Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path,
        agents_root=tmp_path,
        skills_root=tmp_path,
        workflows_root=tmp_path,
        artifact_root=tmp_path,
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/orchestration",
        data={"agent_system": "claude_code", "agent_name": "Primary Agent", "notes": "Use Claude Code"},
        follow_redirects=False,
    )

    assert response.status_code == 303

    page = client.get("/orchestration")
    client.app.dependency_overrides.clear()

    assert page.status_code == 200
    assert "Claude Code" in page.text
    assert "Primary Agent" in page.text
    assert "Use Claude Code" in page.text
    assert (tmp_path / "config" / "orchestration.json").exists()


def test_orchestration_settings_default_parallelism_is_one() -> None:
    assert OrchestrationSettings().execution.max_parallel_tasks == 1


def test_local_model_page_saves_connection_settings(tmp_path) -> None:
    settings = Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path,
        agents_root=tmp_path,
        skills_root=tmp_path,
        workflows_root=tmp_path,
        artifact_root=tmp_path,
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/orchestration/local-model",
        data={"ip_address": "192.168.1.25", "port": "8080", "api_key": "secret", "model_name": "llama"},
        follow_redirects=False,
    )

    assert response.status_code == 303

    page = client.get("/orchestration/local-model")
    client.app.dependency_overrides.clear()

    assert page.status_code == 200
    assert "192.168.1.25" in page.text
    assert ">8080<" in page.text or 'value="8080"' in page.text
    assert "configured" in page.text
    assert (tmp_path / "config" / "orchestration.json").exists()


def test_task_status_form_queue_adds_queue_event(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "draft"}],
            "task_events": [],
        }
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post(
        "/tasks/t1/status",
        data={"status": "queued"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert fake_client.tables["tasks"][0]["status"] == "queued"
    assert [event["event_type"] for event in fake_client.tables["task_events"][:2]] == [
        "status_changed",
        "task_queued",
    ]


def test_local_model_page_rejects_invalid_ip(tmp_path) -> None:
    settings = Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path,
        agents_root=tmp_path,
        skills_root=tmp_path,
        workflows_root=tmp_path,
        artifact_root=tmp_path,
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/orchestration/local-model",
        data={"ip_address": "not_an_ip", "port": "8080"},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_local_model_page_accepts_docker_host_name(tmp_path) -> None:
    settings = Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path,
        agents_root=tmp_path,
        skills_root=tmp_path,
        workflows_root=tmp_path,
        artifact_root=tmp_path,
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/orchestration/local-model",
        data={"ip_address": "host.docker.internal", "port": "12345", "model_name": "borg-cpu"},
        follow_redirects=False,
    )

    page = client.get("/orchestration/local-model")
    client.app.dependency_overrides.clear()

    assert response.status_code == 303
    assert "host.docker.internal" in page.text


def test_workflows_page_renders_yaml_workflow() -> None:
    client = TestClient(create_app())

    response = client.get("/workflows")

    assert response.status_code == 200
    assert "Workflow collective" in response.text
    assert "Assimilation Demo" in response.text
    assert "New Borg Cube Project" in response.text
    assert "Open detail" in response.text
    assert "Level 1" not in response.text
    assert "Borg Queen Architect" not in response.text
    assert "Spezifikation und Umsetzung parallelisieren" not in response.text


def test_workflow_detail_page_renders_execution_view_and_yaml_editor(tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(_workflow_yaml("Demo", "draft"), encoding="utf-8")
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.get("/workflows/demo")

    client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Workflow overview" in response.text
    assert "Execution view" in response.text
    assert "Show YAML source" in response.text
    assert "id: demo" in response.text
    assert "Workflow YAML" in response.text


def test_workflow_detail_page_saves_yaml_file(tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    workflow_file = workflows_root / "demo.yaml"
    workflow_file.write_text(_workflow_yaml("Demo", "draft"), encoding="utf-8")
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/workflows/demo",
        data={"filename": "demo.yaml", "yaml_content": _workflow_yaml("Edited Demo", "queued")},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()

    assert response.status_code == 303
    assert workflow_file.read_text(encoding="utf-8").startswith("id: demo")
    assert "Edited Demo" in workflow_file.read_text(encoding="utf-8")
    assert "status: queued" in workflow_file.read_text(encoding="utf-8")


def test_workflows_api_returns_yaml_workflow() -> None:
    client = TestClient(create_app())

    response = client.get("/api/workflows")

    assert response.status_code == 200
    workflows = response.json()
    assert workflows[0]["id"] == "assimilation-demo"
    assert workflows[0]["entry_node"] == "queen-architect"
    assert {workflow["id"] for workflow in workflows} >= {"assimilation-demo", "new_borg_cube_project"}
    new_cube = next(workflow for workflow in workflows if workflow["id"] == "new_borg_cube_project")
    assert [step["id"] for step in new_cube["steps"]] == [
        "specification-phase",
        "review-phase",
        "disassembly-phase",
        "task-storage-phase",
        "implementation-trigger-phase",
        "implementation-phase",
    ]


def test_workflow_settings_page_edits_yaml_file(tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    workflow_file = workflows_root / "demo.yaml"
    workflow_file.write_text(_workflow_yaml("Demo", "draft"), encoding="utf-8")
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    page = client.get("/workflows/settings?file=demo.yaml")

    assert page.status_code == 200
    assert "Workflow definitions" in page.text
    assert "Demo" in page.text

    updated_yaml = _workflow_yaml("Edited Demo", "queued")
    response = client.post(
        "/workflows/settings",
        data={"filename": "demo.yaml", "yaml_content": updated_yaml},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()

    assert response.status_code == 303
    assert "Edited Demo" in workflow_file.read_text(encoding="utf-8")
    assert "status: queued" in workflow_file.read_text(encoding="utf-8")


def test_workflow_settings_page_rejects_invalid_yaml_without_overwriting(tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    workflow_file = workflows_root / "demo.yaml"
    original_yaml = _workflow_yaml("Demo", "draft")
    workflow_file.write_text(original_yaml, encoding="utf-8")
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/workflows/settings",
        data={"filename": "demo.yaml", "yaml_content": "title: Missing required workflow id"},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "YAML not saved" in response.text
    assert workflow_file.read_text(encoding="utf-8") == original_yaml


def test_html_routes_render_borg_template_for_configuration_errors(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/tasks")

    get_settings.cache_clear()
    assert response.status_code == 503
    assert "text/html" in response.headers["content-type"]
    assert "Node not ready" in response.text
    assert "The local node could not complete the requested operation." in response.text


def test_tasks_page_uses_project_dropdown_from_database(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "draft", "project_id": "example-1"}],
            "projects": [
                {
                    "id": "example-1",
                    "name": "Example 1",
                    "active": True,
                    "default_platform": "Python",
                    "default_mcu": "CPython",
                    "default_board": "PyCharm",
                    "default_topic": "MCP",
                    "project_directory": r"D:\Workbench\firststart",
                    "pycharm_mcp_enabled": True,
                },
                {"id": "example-2", "name": "Example 2", "active": True},
            ],
        }
    )
    settings = Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=Path("."),
        agents_root=Path("."),
        skills_root=Path("."),
        workflows_root=Path("."),
        artifact_root=Path("."),
        supabase_url="http://supabase.local",
        supabase_anon_key="anon",
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.get("/tasks")

    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.text.count('name="project_id"') == 1
    assert response.text.count('name="workflow_id"') == 1
    assert 'name="title"' not in response.text
    assert 'data-platform="Python"' in response.text
    assert r'data-local-path="D:\Workbench\firststart"' in response.text
    assert 'data-pycharm-mcp="1"' in response.text
    assert "Example 1" in response.text
    assert "Example 2" in response.text
    assert "Borg-Scanner" not in response.text
    assert 'name="assigned_agent"' not in response.text
    assert 'name="assigned_skill"' not in response.text


def test_create_task_form_queues_local_llm_workflow_with_project_defaults(monkeypatch, tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(_workflow_yaml("Demo", "draft"), encoding="utf-8")
    fake_client = FakeSupabaseClient(
        {
            "tasks": [],
            "task_events": [],
            "projects": [
                {
                    "id": "first-start",
                    "name": "First Start",
                    "active": True,
                    "default_platform": "Python",
                    "default_mcu": "CPython",
                    "default_board": "PyCharm",
                    "default_topic": "MCP",
                    "project_directory": r"D:\Workbench\firststart",
                    "pycharm_mcp_enabled": True,
                }
            ],
        }
    )
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/tasks",
        data={
            "project_id": "first-start",
            "workflow_id": "demo",
            "description": "Run controlled case manipulation through MCP.",
            "requested_by": "",
        },
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()

    assert response.status_code == 303
    task = fake_client.tables["tasks"][0]
    assert task["title"] == "First Start - Demo"
    assert task["status"] == "queued"
    assert task["workflow_id"] == "demo"
    assert task["assigned_agent"] == "local-llm"
    assert task["assigned_skill"] == "demo"
    assert task["target_platform"] == "Python"
    assert task["target_mcu"] == "CPython"
    assert task["board"] == "PyCharm"
    assert task["local_path"] == r"D:\Workbench\firststart"
    assert task["pycharm_mcp_enabled"] is True
    assert task["topic"] == "MCP"
    assert any(event["event_type"] == "workflow_selected" for event in fake_client.tables["task_events"])


def test_tasks_page_falls_back_when_projects_table_is_unavailable(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "draft", "project_id": "example-1"}],
        }
    )
    settings = Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=Path("."),
        agents_root=Path("."),
        skills_root=Path("."),
        workflows_root=Path("."),
        artifact_root=Path("."),
        supabase_url="http://supabase.local",
        supabase_anon_key="anon",
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings
    
    class FailingProjectRepo:
        def list_projects(self) -> list[dict]:
            raise tasks_module.SupabaseRestError(503, "projects table missing")

    client.app.dependency_overrides[tasks_module.get_project_repository] = lambda: FailingProjectRepo()

    response = client.get("/tasks")

    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "Example 1" in response.text
    assert "Example 2" in response.text
    assert "name=\"project_id\"" in response.text


def test_task_detail_shows_newest_history_entry_first(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "review_required"}],
            "task_events": [
                {"id": "e1", "task_id": "t1", "event_type": "first_step", "message": "Oldest step", "payload": {}, "created_at": "2026-04-12T07:00:00+00:00"},
                {"id": "e2", "task_id": "t1", "event_type": "last_step", "message": "Newest step", "payload": {}, "created_at": "2026-04-12T08:00:00+00:00"},
            ],
            "projects": [],
        }
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/tasks/t1")

    assert response.status_code == 200
    assert response.text.index("last_step") < response.text.index("first_step")
    assert response.text.index("Newest step") < response.text.index("Oldest step")


def test_task_review_confirm_requeues_task(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "Task",
                    "status": "review_required",
                    "description": "Needs review",
                    "pycharm_mcp_enabled": True,
                }
            ],
            "task_events": [],
            "artifacts": [],
            "projects": [],
        }
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.post(
        "/tasks/t1/review",
        data={
            "review_action": "save",
            "action": "confirm",
            "title": "Task",
            "description": "Needs review",
            "review_notes": "Looks good.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/tasks/t1"
    assert fake_client.tables["tasks"][0]["status"] == "queued"
    assert fake_client.tables["tasks"][0]["pycharm_mcp_enabled"] is True
    event_types = [event["event_type"] for event in fake_client.tables["task_events"]]
    assert "review_confirmed" in event_types
    assert "workflow_resumed" in event_types
    assert "task_queued" in event_types


def test_task_review_confirm_resumes_next_unfinished_workflow_level(monkeypatch, tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(_three_stage_workflow_yaml(), encoding="utf-8")
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "review_required", "workflow_id": "demo"}],
            "task_events": [
                {
                    "id": "e1",
                    "task_id": "t1",
                    "event_type": "workflow_stage_completed",
                    "message": "Workflow level 2 completed.",
                    "payload": {"stage_index": 1, "next_stage_index": 2},
                }
            ],
            "artifacts": [],
            "projects": [],
        }
    )
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/tasks/t1/review",
        data={"review_action": "confirm", "review_notes": "Continue."},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 303
    resumed = [
        event for event in fake_client.tables["task_events"] if event["event_type"] == "workflow_resumed"
    ][0]
    assert resumed["payload"]["resume_stage_index"] == 2
    assert fake_client.tables["tasks"][0]["status"] == "queued"


def test_task_review_start_implementation_resumes_trigger_stage(monkeypatch, tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(_implementation_trigger_workflow_yaml(), encoding="utf-8")
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "review_required", "workflow_id": "demo"}],
            "task_events": [
                {
                    "id": "e1",
                    "task_id": "t1",
                    "event_type": "workflow_stage_completed",
                    "message": "Workflow level 1 completed.",
                    "payload": {"stage_index": 0, "next_stage_index": 1},
                }
            ],
            "artifacts": [],
            "projects": [],
        }
    )
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    page = client.get("/tasks/t1/review")
    assert page.status_code == 200
    assert "Start implementation" in page.text
    assert "Trigger implementation task execution" in page.text

    response = client.post(
        "/tasks/t1/review",
        data={"action": "start_implementation", "review_notes": "Start the implementation tasks."},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 303
    resumed = [
        event for event in fake_client.tables["task_events"] if event["event_type"] == "workflow_resumed"
    ][0]
    assert resumed["payload"]["resume_stage_index"] == 2
    assert resumed["payload"]["action"] == "start_implementation"
    assert fake_client.tables["tasks"][0]["status"] == "queued"


def test_task_review_confirm_completes_when_no_workflow_levels_remain(monkeypatch, tmp_path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(_three_stage_workflow_yaml(), encoding="utf-8")
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "review_required", "workflow_id": "demo"}],
            "task_events": [
                {
                    "id": "e1",
                    "task_id": "t1",
                    "event_type": "workflow_stage_completed",
                    "message": "Workflow level 3 completed.",
                    "payload": {"stage_index": 2, "next_stage_index": None},
                }
            ],
            "artifacts": [],
            "projects": [],
        }
    )
    settings = _test_settings(tmp_path, workflows_root=workflows_root)
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())
    client.app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/tasks/t1/review",
        data={"review_action": "confirm", "review_notes": "Done."},
        follow_redirects=False,
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 303
    assert fake_client.tables["tasks"][0]["status"] == "done"
    event_types = [event["event_type"] for event in fake_client.tables["task_events"]]
    assert "workflow_completed" in event_types
    assert "task_queued" not in event_types


def test_task_review_can_cancel_task(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "review_required", "description": "Needs review"}],
            "task_events": [],
            "artifacts": [],
            "projects": [],
        }
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    page = client.get("/tasks/t1/review")
    assert page.status_code == 200
    assert 'value="cancel"' in page.text

    response = client.post(
        "/tasks/t1/review",
        data={
            "review_action": "cancel",
            "title": "Task",
            "description": "Needs review",
            "review_notes": "Stop this task.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/tasks/t1"
    assert fake_client.tables["tasks"][0]["status"] == "cancelled"
    assert any(event["event_type"] == "review_cancelled" for event in fake_client.tables["task_events"])


def test_task_review_page_shows_latest_llm_summary(monkeypatch) -> None:
    fake_client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task", "status": "review_required", "description": "Needs review"}],
            "task_events": [
                {
                    "id": "e1",
                    "task_id": "t1",
                    "event_type": "llm_request",
                    "message": "LLM request sent for human review.",
                    "payload": {"iteration": 1, "prompt": "What should I do?"},
                    "created_at": "2026-04-12T07:59:00+00:00",
                },
                {
                    "id": "e2",
                    "task_id": "t1",
                    "event_type": "llm_response",
                    "message": "LLM response received for human review.",
                    "payload": {"iteration": 1, "response": "Please inspect the task."},
                    "created_at": "2026-04-12T07:59:30+00:00",
                },
                {
                    "id": "e3",
                    "task_id": "t1",
                    "event_type": "llm_processing_completed",
                    "message": "Local LLM processing completed; workflow node selection can begin.",
                    "payload": {
                        "summary": "Verify directory structure and existing main.py in D:\\\\Workbench\\\\firststart using MCP",
                        "human_review_text": "Iteration 1\nPrompt:\nWhat should I do?\nResponse:\nPlease inspect the task.",
                    },
                    "created_at": "2026-04-12T08:00:00+00:00",
                }
            ],
            "artifacts": [],
            "projects": [],
        }
    )
    monkeypatch.setattr(tasks_module, "SupabaseRestClient", lambda _settings: fake_client)
    client = TestClient(create_app())

    response = client.get("/tasks/t1/review")

    assert response.status_code == 200
    assert "LLM summary for review" in response.text
    assert "Verify directory structure and existing main.py" in response.text
    assert "llm_processing_completed" in response.text
    assert "LLM transcript" in response.text
    assert "What should I do?" in response.text
    assert "Please inspect the task." in response.text
    assert "LLM output for review" in response.text


def test_api_routes_keep_json_errors_for_configuration_errors(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/api/tasks")

    get_settings.cache_clear()
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert "SUPABASE_URL is not configured" in response.json()["detail"]


def _test_settings(tmp_path: Path, workflows_root: Path | None = None) -> Settings:
    return Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path,
        agents_root=tmp_path,
        skills_root=tmp_path,
        workflows_root=workflows_root or tmp_path,
        artifact_root=tmp_path,
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )


def _workflow_yaml(title: str, status_value: str) -> str:
    return f"""id: demo
title: {title}
description: Editable workflow.
status: {status_value}
entry_node: coordinator
nodes:
  - id: coordinator
    borg_name: Coordinator
    role: coordinator
    agent: codex
    tasks:
      - id: intake
        title: Intake
        prompt: Start the workflow.
        status: draft
steps:
  - id: intake
    title: Start
    mode: sequential
    nodes:
      - coordinator
"""


def _three_stage_workflow_yaml() -> str:
    return """id: demo
title: Demo
description: Three stage workflow.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Intake
    agent: local-llm
    tasks:
      - id: intake-task
        title: Intake
        prompt: Intake.
  - id: implement
    borg_name: Implement
    agent: local-llm
    tasks:
      - id: implementation-plan
        title: Implement
        prompt: Implement.
  - id: verify
    borg_name: Verify
    agent: local-llm
    tasks:
      - id: verification
        title: Verify
        prompt: Verify.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
  - id: implementation
    title: Implementation
    mode: sequential
    nodes:
      - implement
  - id: verification
    title: Verification
    mode: sequential
    nodes:
      - verify
"""


def _implementation_trigger_workflow_yaml() -> str:
    return """id: demo
title: Demo
description: Implementation trigger workflow.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Intake
    agent: local-llm
    tasks:
      - id: intake-task
        title: Intake
        prompt: Intake.
  - id: storage
    borg_name: Task Storage
    agent: borg-disassembler
    tasks:
      - id: store-tasks
        title: Store tasks
        prompt: Store tasks.
  - id: trigger
    borg_name: Implementation Trigger
    role: implementation_trigger
    agent: borg-disassembler
    tasks:
      - id: trigger-implementation
        title: Trigger implementation
        prompt: Queue stored implementation tasks.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
  - id: task-storage-phase
    title: Store generated implementation tasks
    mode: sequential
    nodes:
      - storage
  - id: implementation-trigger-phase
    title: Trigger implementation task execution
    mode: sequential
    nodes:
      - trigger
"""
