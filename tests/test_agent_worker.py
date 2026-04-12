from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.db.repositories import ArtifactRepository, TaskRepository
from app.services.agent_worker import AgentWorker
from app.services.orchestration_settings_store import (
    AgentSelectionSettings,
    ExecutionSettings,
    LocalModelSettings,
    OrchestrationSettingsStore,
)
from tests.fakes import FakeSupabaseClient


class FakeLocalLlmClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def send_prompt(self, prompt: str) -> dict[str, str]:
        self.calls.append(prompt)
        if len(self.calls) == 3:
            return {"content": '{"first_node_id": "intake", "summary": "Start with intake."}'}
        return {"content": '{"summary": "Plan next steps."}'}


class FakeClaudeCodeClient:
    def __init__(self, project_root: str = "D:\\Workbench\\borg-universe") -> None:
        self.prompts: list[str] = []
        self.project_root = project_root

    def ensure_project_assets(self) -> dict[str, object]:
        return {
            "project_root": self.project_root,
            "local_claude_root": f"{self.project_root}\\.claude",
            "global_agents_exists": False,
            "local_agents_exists": True,
            "global_skills_exists": False,
            "local_skills_exists": True,
            "agents": [".claude\\agents\\borg-queen-architect.md"],
            "skills": [".claude\\skills\\borg-cube-printer\\SKILL.md"],
        }

    def send_prompt(self, prompt: str) -> dict[str, object]:
        self.prompts.append(prompt)
        return {
            "content": '{"first_node_id": "intake", "summary": "Claude delegated to Borg agents.", "borg_cube_md": "# Feature Specification\\n\\nDemo\\n"}',
            "response": {"result": "Claude delegated to Borg agents.", "borg_cube_md": "# Feature Specification\n\nDemo\n"},
            "command": ["claude", "-p", "<prompt>", "--model", "borg-cpu"],
            "stderr": "",
        }


def test_worker_uses_web_parallelism_and_runs_workflow_nodes_in_order(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Sequential worker test.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Intake Agent
    agent: local-llm
    tasks:
      - id: normalize
        title: Normalize request
        prompt: Normalize the task.
  - id: execute
    borg_name: Execute Agent
    agent: local-llm
    tasks:
      - id: execute-skill
        title: Execute task
        prompt: Execute the task.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
  - id: execute
    title: Execute
    mode: sequential
    nodes:
      - execute
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    OrchestrationSettingsStore(settings.borg_root).save(execution=ExecutionSettings(max_parallel_tasks=2))
    client = FakeSupabaseClient(
        {
            "tasks": [
                {"id": "t1", "title": "Task 1", "status": "queued", "workflow_id": "demo", "assigned_agent": "local-llm"},
                {"id": "t2", "title": "Task 2", "status": "queued", "workflow_id": "demo", "assigned_agent": "local-llm"},
                {"id": "t3", "title": "Task 3", "status": "queued", "workflow_id": "demo", "assigned_agent": "local-llm"},
            ],
            "task_events": [],
            "artifacts": [],
        }
    )
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        local_llm_client=FakeLocalLlmClient(),
    )

    processed = worker.process_next_batch()

    assert processed == 2
    assert [task["status"] for task in client.tables["tasks"]] == ["review_required", "review_required", "queued"]
    t1_invocations = [
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "workflow_agent_invoked"
    ]
    assert [event["payload"]["node_id"] for event in t1_invocations] == ["intake"]
    t1_llm_events = [
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "llm_iteration_completed"
    ]
    assert [event["payload"]["iteration"] for event in t1_llm_events] == [1, 2, 3]
    request_events = [
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "llm_request"
    ]
    response_events = [
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "llm_response"
    ]
    assert [event["payload"]["iteration"] for event in request_events] == [1, 2, 3]
    assert [event["payload"]["iteration"] for event in response_events] == [1, 2, 3]
    completed_event = next(
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "llm_processing_completed"
    )
    assert "human_review_text" in completed_event["payload"]
    assert "Iteration 1" in completed_event["payload"]["human_review_text"]
    first_node_event = next(
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "workflow_first_node_selected"
    )
    assert first_node_event["payload"]["node_id"] == "intake"
    t1_skill_events = [
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "workflow_skills_selected"
    ]
    assert t1_skill_events[0]["payload"]["skills"] == ["normalize"]
    stage_event = next(
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "workflow_stage_completed"
    )
    assert stage_event["payload"]["stage_index"] == 0
    assert stage_event["payload"]["next_stage_index"] == 1
    no_change_event = next(
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "no_file_changes_applied"
    )
    assert no_change_event["payload"]["applied"] is False
    assert "No file changes" in no_change_event["message"]


def test_worker_includes_review_context_in_llm_prompt(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Sequential worker test.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Intake Agent
    agent: local-llm
    tasks:
      - id: normalize
        title: Normalize request
        prompt: Normalize the task.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "Task 1",
                    "status": "queued",
                    "workflow_id": "demo",
                    "assigned_agent": "local-llm",
                    "pycharm_mcp_enabled": True,
                }
            ],
            "task_events": [
                {
                    "id": "r1",
                    "task_id": "t1",
                    "event_type": "review_noted",
                    "message": "Review notes were recorded.",
                    "payload": {"notes": "Please keep the generated summary and continue."},
                },
                {
                    "id": "r2",
                    "task_id": "t1",
                    "event_type": "llm_processing_completed",
                    "message": "Local LLM processing completed; workflow node selection can begin.",
                    "payload": {
                        "summary": "Use the existing summary for the next step.",
                        "human_review_text": "Iteration 1\nResponse:\nDraft the next step.",
                    },
                },
            ],
            "artifacts": [],
        }
    )
    llm = FakeLocalLlmClient()
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        local_llm_client=llm,
    )

    worker.process_next_batch()

    assert "Human review context:" in llm.calls[0]
    assert "Please keep the generated summary and continue." in llm.calls[0]
    assert "Use the existing summary for the next step." in llm.calls[0]
    assert "Iteration 1" in llm.calls[0]


def test_worker_delegates_borg_cpu_tasks_to_claude_code_with_project_agents(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Claude Code delegation test.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Queen
    agent: borg-queen-architect
    tasks:
      - id: architecture-planning
        title: Plan architecture
        prompt: Route this through the queen architect.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    OrchestrationSettingsStore(settings.borg_root).save(
        agent_selection=AgentSelectionSettings(agent_system="local_model", agent_name="borg-cpu"),
        local_model=LocalModelSettings(
            ip_address="host.docker.internal",
            port=12345,
            api_key="lmstudio",
            model_name="borg-cpu",
        ),
    )
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "Task 1",
                    "description": "Implement the requested change.",
                    "status": "queued",
                    "workflow_id": "demo",
                    "assigned_agent": "local-llm",
                    "local_path": r"D:\Workbench\target",
                }
            ],
            "task_events": [],
            "artifacts": [],
        }
    )
    claude = FakeClaudeCodeClient(project_root=str(tmp_path))
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        claude_code_client=claude,
    )

    worker.process_next_batch()

    assert len(claude.prompts) == 1
    assert "Use project subagents from `.claude/agents`" in claude.prompts[0]
    assert "`borg-queen-architect` subagent" in claude.prompts[0]
    assert "node_id=intake; agent=borg-queen-architect" in claude.prompts[0]
    event_types = [event["event_type"] for event in client.tables["task_events"]]
    assert "claude_assets_synced" in event_types
    assert "llm_processing_completed" in event_types
    completed_event = next(
        event for event in client.tables["task_events"] if event["event_type"] == "llm_processing_completed"
    )
    assert completed_event["payload"]["provider"] == "claude_code"
    assert completed_event["payload"]["first_node_id"] == "intake"
    assert (tmp_path / "borg-cube.md").exists()
    assert "Feature Specification" in (tmp_path / "borg-cube.md").read_text(encoding="utf-8")
    assert any(event["event_type"] == "borg_cube_written" for event in client.tables["task_events"])
    assert client.tables["tasks"][0]["status"] == "review_required"


def test_worker_passes_pycharm_mcp_config_from_project_to_claude_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Claude Code delegation test.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Queen
    agent: borg-queen-architect
    tasks:
      - id: architecture-planning
        title: Plan architecture
        prompt: Route this through the queen architect.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    OrchestrationSettingsStore(settings.borg_root).save(
        agent_selection=AgentSelectionSettings(agent_system="local_model", agent_name="borg-cpu"),
        local_model=LocalModelSettings(
            ip_address="host.docker.internal",
            port=12345,
            api_key="lmstudio",
            model_name="borg-cpu",
        ),
    )
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "Task 1",
                    "description": "Implement the requested change.",
                    "status": "queued",
                    "workflow_id": "demo",
                    "assigned_agent": "local-llm",
                    "project_id": "project-1",
                    "local_path": r"D:\Workbench\firststart",
                    "pycharm_mcp_enabled": True,
                }
            ],
            "projects": [
                {
                    "id": "project-1",
                    "name": "Automation Tools",
                    "pycharm_mcp_enabled": True,
                    "pycharm_mcp_sse_url": "http://127.0.0.1:64769/sse",
                    "pycharm_mcp_stream_url": "http://127.0.0.1:64769/stream",
                }
            ],
            "task_events": [],
            "artifacts": [],
        }
    )
    captured: dict[str, object] = {}

    class CapturingClaudeCodeClient:
        def __init__(self, *, settings, orchestration, workspace=None, runner=None, timeout_seconds=None, mcp_config_json=None):
            captured["mcp_config_json"] = mcp_config_json
            captured["project_root"] = str(workspace.project_root) if workspace else None
            self.prompts: list[str] = []

        def ensure_project_assets(self) -> dict[str, object]:
            return {
                "project_root": str(tmp_path),
                "local_claude_root": f"{tmp_path}\\.claude",
                "global_agents_exists": False,
                "local_agents_exists": True,
                "global_skills_exists": False,
                "local_skills_exists": True,
                "agents": [".claude\\agents\\borg-queen-architect.md"],
                "skills": [".claude\\skills\\borg-cube-printer\\SKILL.md"],
            }

        def send_prompt(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            captured["prompt"] = prompt
            return {
                "content": '{"first_node_id": "intake", "summary": "Claude delegated to Borg agents.", "borg_cube_md": "# Feature Specification\\n\\nDemo\\n"}',
                "response": {"result": "Claude delegated to Borg agents.", "borg_cube_md": "# Feature Specification\n\nDemo\n"},
                "command": ["claude", "--bare", "--no-session-persistence", "-p", "<prompt>", "--model", "borg-cpu", "--output-format", "json"],
                "stderr": "",
            }

    monkeypatch.setattr("app.services.agent_worker.ClaudeCodeClient", CapturingClaudeCodeClient)

    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
    )

    worker.process_next_batch()

    assert json.loads(str(captured["mcp_config_json"])) == {
        "mcpServers": {
            "pycharm": {
                "type": "http",
                "url": "http://127.0.0.1:64769/stream",
            }
        }
    }
    assert str(captured["project_root"]).replace("\\", "/") == "/workbench/firststart"
    prompt_text = str(captured["prompt"]).replace("\\", "/")
    assert "Use the PyCharm MCP file tools" in prompt_text
    assert "Target project path on host: D:/Workbench/firststart" in prompt_text
    assert "Target project path in container: /workbench/firststart" in prompt_text
    assert client.tables["tasks"][0]["status"] == "review_required"


def test_worker_resume_after_review_forwards_notes_to_llm_and_runs_next_workflow_level(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Sequential worker test.
status: draft
entry_node: intake
nodes:
  - id: intake
    borg_name: Intake Agent
    agent: local-llm
    tasks:
      - id: normalize
        title: Normalize request
        prompt: Normalize the task.
  - id: spec
    borg_name: Spec Agent
    agent: local-llm
    tasks:
      - id: spec-review
        title: Review spec
        prompt: Review the spec.
  - id: implement
    borg_name: Implementation Agent
    agent: local-llm
    tasks:
      - id: implementation-plan
        title: Implement task
        prompt: Implement the task.
steps:
  - id: intake
    title: Intake
    mode: sequential
    nodes:
      - intake
  - id: parallel-analysis
    title: Implementation
    mode: parallel
    nodes:
      - spec
      - implement
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [
                {"id": "t1", "title": "Task 1", "status": "queued", "workflow_id": "demo", "assigned_agent": "local-llm"}
            ],
            "task_events": [
                {
                    "id": "n1",
                    "task_id": "t1",
                    "event_type": "review_noted",
                    "message": "Review notes were recorded.",
                    "payload": {"notes": "Proceed with implementation and keep the scope small."},
                },
                {
                    "id": "l1",
                    "task_id": "t1",
                    "event_type": "llm_processing_completed",
                    "message": "Local LLM processing completed; workflow node selection can begin.",
                    "payload": {
                        "summary": "Existing implementation plan.",
                        "human_review_text": "Iteration 1\nResponse:\nPlan the implementation.",
                    },
                },
                {
                    "id": "r1",
                    "task_id": "t1",
                    "event_type": "workflow_resumed",
                    "message": "Review completed; implementation begins and the workflow chain resumes.",
                    "payload": {"resume_stage_index": 1},
                }
            ],
            "artifacts": [],
        }
    )
    llm = FakeLocalLlmClient()
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        local_llm_client=llm,
    )

    worker.process_next_batch()

    assert len(llm.calls) == 1
    assert "Proceed with implementation and keep the scope small." in llm.calls[0]
    assert "Existing implementation plan." in llm.calls[0]
    assert "do not choose or change the first node" in llm.calls[0]
    assert "Select the first workflow node" not in llm.calls[0]
    invocations = [
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "workflow_agent_invoked"
    ]
    assert [event["payload"]["node_id"] for event in invocations] == ["spec", "implement"]
    assert {event["payload"]["stage_index"] for event in invocations} == {1}
    assert any(
        event.get("task_id") == "t1" and event["event_type"] == "implementation_started"
        for event in client.tables["task_events"]
    )
    resume_event = next(
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "workflow_resume_detected"
    )
    assert resume_event["payload"]["has_review_notes"] is True
    completed_event = next(
        event
        for event in client.tables["task_events"]
        if event.get("task_id") == "t1" and event["event_type"] == "llm_resume_processing_completed"
    )
    assert completed_event["payload"]["resume_stage_index"] == 1


def _settings(tmp_path: Path, workflows_root: Path) -> Settings:
    return Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path,
        agents_root=tmp_path,
        skills_root=tmp_path,
        workflows_root=workflows_root,
        artifact_root=tmp_path,
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=4,
    )
