from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.db.repositories import ArtifactRepository, TaskRepository
from app.db.supabase_client import SupabaseRestError
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
    assert "Workspace write discipline:" in claude.prompts[0]
    assert "Use relative paths from the workspace" in claude.prompts[0]
    assert "instead of `mkdir -p /workbench/project/modules/name`" in claude.prompts[0]
    event_types = [event["event_type"] for event in client.tables["task_events"]]
    assert "claude_assets_synced" in event_types
    assert "llm_processing_completed" in event_types
    completed_event = next(
        event for event in client.tables["task_events"] if event["event_type"] == "llm_processing_completed"
    )
    assert completed_event["payload"]["provider"] == "claude_code"
    assert completed_event["payload"]["first_node_id"] == "intake"
    assert "project_specs" in client.tables
    assert client.tables["project_specs"][0]["spec_path"] == "borg-cube.md"
    assert "Feature Specification" in client.tables["project_specs"][0]["content"]
    assert any(event["event_type"] == "borg_cube_specs_stored" for event in client.tables["task_events"])
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
    target_project = tmp_path / "firststart"
    target_project.mkdir()
    (target_project / "pyproject.toml").write_text(
        "[project]\nname = \"firststart\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
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
                    "local_path": str(target_project),
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
    assert str(captured["project_root"]) == str(target_project)
    prompt_text = str(captured["prompt"]).replace("\\", "/")
    assert "Use the PyCharm MCP file tools" in prompt_text
    assert f"Target project path on host: {str(target_project).replace(chr(92), '/')}" in prompt_text
    assert "Detected markers: pyproject.toml" in prompt_text
    assert client.tables["tasks"][0]["status"] == "review_required"


def test_worker_stores_structured_borg_cube_specs_and_implementation_tasks(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Structured borg-cube persistence test.
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
        local_model=LocalModelSettings(model_name="borg-cpu"),
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
                }
            ],
            "task_events": [],
            "artifacts": [],
            "project_specs": [],
        }
    )

    class StructuredClaudeCodeClient(FakeClaudeCodeClient):
        def send_prompt(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            return {
                "content": json.dumps(
                    {
                        "first_node_id": "intake",
                        "summary": "Structured specs and tasks ready.",
                        "borg_cube_specs": [
                            {
                                "spec_path": "borg-cube.md",
                                "spec_type": "project",
                                "title": "Project Cube",
                                "summary": "Root project description.",
                                "content": "# Project Cube\n\n## Modules\n- module-a/borg-cube.md\n",
                            },
                            {
                                "spec_path": "module-a/borg-cube.md",
                                "spec_type": "module",
                                "module_name": "module-a",
                                "title": "Module A",
                                "summary": "Capabilities for module A.",
                                "content": "# Module A\n\nCapabilities: one small behavior.\n",
                            },
                        ],
                        "implementation_tasks": [
                            {"title": "Build module A parser", "prompt": "Implement only the parser."},
                            {"title": "Build module A tests", "prompt": "<nano-implant> Add focused parser tests."},
                        ],
                    }
                ),
                "response": {},
                "command": ["claude", "-p", "<prompt>", "--model", "borg-cpu"],
                "stderr": "",
            }

    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        claude_code_client=StructuredClaudeCodeClient(project_root=str(tmp_path)),
    )

    worker.process_next_batch()

    assert [spec["spec_path"] for spec in client.tables["project_specs"]] == ["borg-cube.md", "module-a/borg-cube.md"]
    assert client.tables["project_specs"][0]["project_id"] == "project-1"
    created_tasks = [task for task in client.tables["tasks"] if task["id"] != "t1"]
    assert [task["assigned_agent"] for task in created_tasks] == ["borg-implementation-drone", "borg-implementation-drone"]
    assert [task.get("workflow_id") for task in created_tasks] == [None, None]
    assert [task["status"] for task in created_tasks] == ["draft", "draft"]
    assert all(task["description"].startswith("<nano-implant>") for task in created_tasks)
    assert any(event["event_type"] == "implementation_tasks_created" for event in client.tables["task_events"])


def test_new_borg_cube_project_materializes_base_project_and_specs(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    project_root = tmp_path / "newcube"
    project_root.mkdir()
    (workflows_root / "new_borg_cube_project.yaml").write_text(
        """id: new_borg_cube_project
title: New Borg Cube Project
description: Create scaffold and specs.
status: queued
entry_node: queen-architect
nodes:
  - id: queen-architect
    borg_name: Queen
    agent: borg-queen-architect
    tasks:
      - id: architecture-planning
        title: Create base project and module borg-cube specs
        prompt: Create a minimal base project and borg-cube specs.
steps:
  - id: specification-phase
    title: Specification
    mode: sequential
    nodes:
      - queen-architect
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    OrchestrationSettingsStore(settings.borg_root).save(
        agent_selection=AgentSelectionSettings(agent_system="local_model", agent_name="borg-cpu"),
        local_model=LocalModelSettings(model_name="borg-cpu"),
    )
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "New cube",
                    "description": "Create a new Python helper project.",
                    "status": "queued",
                    "workflow_id": "new_borg_cube_project",
                    "assigned_agent": "local-llm",
                    "project_id": "project-1",
                    "local_path": str(project_root),
                }
            ],
            "task_events": [],
            "artifacts": [],
            "project_specs": [],
        }
    )

    class ScaffoldClaudeCodeClient(FakeClaudeCodeClient):
        def send_prompt(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            root_spec = """# New Cube

## Metadata
- Status: draft

## Goal
Create a Python helper project.

## Problem Statement
The project needs a clean starting point.

## Scope
- In scope: package scaffold and specs.
- Out of scope: production feature code.

## Dependencies
- Python 3 runtime.

## Submodules / Internal Structure
- src/newcube/borg-cube.md: core package module.

## Functional Requirements
- FR-001: The project shall provide an importable package.

## Non-Functional Requirements
- NFR-001: The scaffold shall run without network access.

## Constraints
- Use safe relative paths only.

## Interfaces
- Package import: newcube.

## Error Handling
- Invalid input shall be reported by future tasks.

## Assumptions / Open Points
- No external service is required.
"""
            return {
                "content": json.dumps(
                    {
                        "first_node_id": "queen-architect",
                        "summary": "Base project and specs ready.",
                        "materialize_borg_cube_files": True,
                        "borg_cube_specs": [
                            {
                                "spec_path": "borg-cube.md",
                                "spec_type": "project",
                                "title": "New Cube",
                                "summary": "Python helper project.",
                                "content": root_spec,
                            },
                            {
                                "spec_path": "src/newcube/borg-cube.md",
                                "spec_type": "module",
                                "module_name": "newcube",
                                "title": "newcube",
                                "summary": "Core package.",
                                "content": "# newcube\n\nCore package capabilities.\n",
                            },
                        ],
                        "project_files": [
                            {"path": "README.md", "content": "# New Cube\n"},
                            {"path": "pyproject.toml", "content": "[project]\nname = \"newcube\"\nversion = \"0.1.0\"\n"},
                            {"path": "src/newcube/__init__.py", "content": "__all__ = []\n"},
                            {"path": "../outside.txt", "content": "must not be written\n"},
                        ],
                    }
                ),
                "response": {},
                "command": ["claude", "-p", "<prompt>", "--model", "borg-cpu"],
                "stderr": "",
            }

    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        claude_code_client=ScaffoldClaudeCodeClient(project_root=str(project_root)),
    )

    worker.process_next_batch()

    assert (project_root / "borg-cube.md").read_text(encoding="utf-8").startswith("# New Cube")
    assert (project_root / "src" / "newcube" / "borg-cube.md").read_text(encoding="utf-8").startswith("# newcube")
    assert (project_root / "README.md").read_text(encoding="utf-8").startswith("# New Cube")
    assert (project_root / "pyproject.toml").exists()
    assert (project_root / "src" / "newcube" / "__init__.py").exists()
    assert not (tmp_path / "outside.txt").exists()
    event_types = [event["event_type"] for event in client.tables["task_events"]]
    assert "borg_cube_specs_stored" in event_types
    assert "project_files_materialized" in event_types
    assert "borg_cube_spec_validated" in event_types


def test_new_borg_cube_project_fails_when_root_spec_is_not_clean(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    project_root = tmp_path / "badcube"
    project_root.mkdir()
    (workflows_root / "new_borg_cube_project.yaml").write_text(
        """id: new_borg_cube_project
title: New Borg Cube Project
description: Create scaffold and specs.
status: queued
entry_node: queen-architect
nodes:
  - id: queen-architect
    borg_name: Queen
    agent: borg-queen-architect
    tasks:
      - id: architecture-planning
        title: Create base project and module borg-cube specs
        prompt: Create a minimal base project and borg-cube specs.
steps:
  - id: specification-phase
    title: Specification
    mode: sequential
    nodes:
      - queen-architect
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    OrchestrationSettingsStore(settings.borg_root).save(
        agent_selection=AgentSelectionSettings(agent_system="local_model", agent_name="borg-cpu"),
        local_model=LocalModelSettings(model_name="borg-cpu"),
    )
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "Bad cube",
                    "description": "Create a new project.",
                    "status": "queued",
                    "workflow_id": "new_borg_cube_project",
                    "assigned_agent": "local-llm",
                    "project_id": "project-1",
                    "local_path": str(project_root),
                }
            ],
            "task_events": [],
            "artifacts": [],
            "project_specs": [],
        }
    )

    class BadSpecClaudeCodeClient(FakeClaudeCodeClient):
        def send_prompt(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            return {
                "content": json.dumps(
                    {
                        "first_node_id": "queen-architect",
                        "summary": "Incomplete spec.",
                        "materialize_borg_cube_files": True,
                        "borg_cube_specs": [
                            {
                                "spec_path": "borg-cube.md",
                                "spec_type": "project",
                                "title": "Bad Cube",
                                "summary": "Incomplete.",
                                "content": "# Bad Cube\n\nDemo\n",
                            }
                        ],
                    }
                ),
                "response": {},
                "command": ["claude", "-p", "<prompt>", "--model", "borg-cpu"],
                "stderr": "",
            }

    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        claude_code_client=BadSpecClaudeCodeClient(project_root=str(project_root)),
    )

    result = worker.process_task(client.tables["tasks"][0])

    assert result["status"] == "failed"
    assert client.tables["tasks"][0]["status"] == "failed"
    failed_event = next(event for event in client.tables["task_events"] if event["event_type"] == "borg_cube_spec_validation_failed")
    assert "missing section: metadata" in failed_event["payload"]["errors"]
    assert "missing traceable FR-* functional requirements" in failed_event["payload"]["errors"]


def test_worker_triggers_stored_implementation_tasks_from_workflow_stage(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Implementation trigger test.
status: draft
entry_node: trigger
nodes:
  - id: trigger
    borg_name: Implementation Trigger
    role: implementation_trigger
    agent: borg-disassembler
    tasks:
      - id: trigger-implementation
        title: Trigger implementation
        prompt: Queue stored implementation tasks.
steps:
  - id: implementation-trigger-phase
    title: Trigger implementation task execution
    mode: sequential
    nodes:
      - trigger
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "parent",
                    "title": "Parent",
                    "status": "queued",
                    "workflow_id": "demo",
                    "assigned_agent": "local-llm",
                },
                {
                    "id": "child-1",
                    "title": "Implement A",
                    "description": "<nano-implant> A\n\nParent task: parent",
                    "status": "draft",
                    "assigned_agent": "borg-implementation-drone",
                },
                {
                    "id": "child-2",
                    "title": "Implement B",
                    "description": "<nano-implant> B\n\nParent task: parent",
                    "status": "review_required",
                    "assigned_agent": "borg-implementation-drone",
                },
                {
                    "id": "child-3",
                    "title": "Already done",
                    "description": "<nano-implant> C\n\nParent task: parent",
                    "status": "done",
                    "assigned_agent": "borg-implementation-drone",
                },
            ],
            "task_events": [
                {
                    "id": "resume",
                    "task_id": "parent",
                    "event_type": "workflow_resumed",
                    "message": "Resume implementation trigger.",
                    "payload": {"resume_stage_index": 0},
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

    statuses = {task["id"]: task["status"] for task in client.tables["tasks"]}
    assert statuses["child-1"] == "queued"
    assert statuses["child-2"] == "queued"
    assert statuses["child-3"] == "done"
    trigger_event = next(event for event in client.tables["task_events"] if event["event_type"] == "implementation_stage_triggered")
    assert trigger_event["payload"]["task_ids"] == ["child-1", "child-2"]
    child_events = [
        event for event in client.tables["task_events"] if event["event_type"] == "implementation_triggered"
    ]
    assert {event["task_id"] for event in child_events} == {"child-1", "child-2"}


def test_worker_start_implementation_bypasses_sparse_parent_project_guard(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    sparse_project = tmp_path / "firststart"
    (sparse_project / ".claude").mkdir(parents=True)
    (sparse_project / ".venv").mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Implementation trigger test.
status: draft
entry_node: trigger
nodes:
  - id: trigger
    borg_name: Implementation Trigger
    role: implementation_trigger
    agent: borg-disassembler
    tasks:
      - id: trigger-implementation
        title: Trigger implementation
        prompt: Queue stored implementation tasks.
steps:
  - id: implementation-trigger-phase
    title: Trigger implementation task execution
    mode: sequential
    nodes:
      - trigger
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "parent",
                    "title": "Parent",
                    "description": "Start implementation for sparse firststart project.",
                    "status": "queued",
                    "workflow_id": "demo",
                    "assigned_agent": "local-llm",
                    "local_path": str(sparse_project),
                },
                {
                    "id": "child-1",
                    "title": "Child 1",
                    "description": "<nano-implant> Implement one focused task.\n\nParent task: parent",
                    "status": "draft",
                    "assigned_agent": "borg-implementation-drone",
                    "local_path": str(sparse_project),
                },
            ],
            "task_events": [
                {
                    "id": "resume",
                    "task_id": "parent",
                    "event_type": "workflow_resumed",
                    "message": "Review completed; implementation begins.",
                    "payload": {"resume_stage_index": 0, "action": "start_implementation"},
                }
            ],
            "artifacts": [],
        }
    )
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        local_llm_client=FakeLocalLlmClient(),
    )

    worker.process_next_batch()

    statuses = {task["id"]: task["status"] for task in client.tables["tasks"]}
    assert statuses["child-1"] == "queued"
    assert "project_context_missing" not in [event["event_type"] for event in client.tables["task_events"]]
    assert any(event["event_type"] == "implementation_stage_triggered" for event in client.tables["task_events"])


def test_worker_executes_nano_implant_task_with_implementation_drone(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    settings = _settings(tmp_path, workflows_root)
    OrchestrationSettingsStore(settings.borg_root).save(
        agent_selection=AgentSelectionSettings(agent_system="local_model", agent_name="borg-cpu"),
        local_model=LocalModelSettings(model_name="borg-cpu"),
    )
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "child-1",
                    "title": "Implement greeting",
                    "description": "<nano-implant> Implement the greeting button.\n\nParent task: parent",
                    "status": "queued",
                    "assigned_agent": "borg-implementation-drone",
                    "project_id": "project-1",
                    "local_path": r"D:\Workbench\firststart",
                }
            ],
            "task_events": [],
            "artifacts": [],
            "project_specs": [
                {
                    "project_id": "project-1",
                    "spec_path": "borg-cube.md",
                    "title": "Project Cube",
                    "summary": "Greeting app.",
                    "content": "# Project Cube\n\nGreeting app.",
                }
            ],
        }
    )

    class ImplementationClaudeCodeClient(FakeClaudeCodeClient):
        def send_prompt(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            return {
                "content": json.dumps(
                    {
                        "summary": "Greeting button implemented.",
                        "modified_files": ["main.py"],
                        "tests": ["manual verification"],
                        "verification": "passed",
                    }
                ),
                "response": {},
                "command": ["claude", "-p", "<prompt>", "--model", "borg-cpu"],
                "stderr": "",
            }

    claude = ImplementationClaudeCodeClient(project_root=str(tmp_path))
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        claude_code_client=claude,
    )

    worker.process_next_batch()

    assert client.tables["tasks"][0]["status"] == "done"
    assert claude.prompts[0].startswith("<nano-implant>")
    assert "Run the `borg-implementation-drone` subagent" in claude.prompts[0]
    assert "Workspace write discipline:" in claude.prompts[0]
    assert "Do not create or edit files by prefixing the absolute workspace path." in claude.prompts[0]
    assert "retry once with one simple relative command" in claude.prompts[0]
    assert "Stored borg-cube specs:" in claude.prompts[0]
    event_types = [event["event_type"] for event in client.tables["task_events"]]
    assert "implementation_task_started" in event_types
    assert "implementation_task_completed" in event_types


def test_worker_continues_when_project_spec_storage_is_unavailable(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Spec storage fallback test.
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
        local_model=LocalModelSettings(model_name="borg-cpu"),
    )

    class FailingProjectSpecsClient(FakeSupabaseClient):
        def request(self, method, path, *, query=None, body=None, prefer=None):  # type: ignore[override]
            if method.upper() == "POST" and path.strip("/") == "project_specs":
                raise SupabaseRestError(404, "{}")
            return super().request(method, path, query=query, body=body, prefer=prefer)

    client = FailingProjectSpecsClient(
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
                }
            ],
            "task_events": [],
            "artifacts": [],
            "project_specs": [],
        }
    )

    class StructuredClaudeCodeClient(FakeClaudeCodeClient):
        def send_prompt(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            return {
                "content": json.dumps(
                    {
                        "first_node_id": "intake",
                        "summary": "Structured specs and tasks ready.",
                        "borg_cube_specs": [
                            {
                                "spec_path": "borg-cube.md",
                                "spec_type": "project",
                                "title": "Project Cube",
                                "summary": "Root project description.",
                                "content": "# Project Cube\n\n## Modules\n- module-a/borg-cube.md\n",
                            }
                        ],
                        "implementation_tasks": [
                            {"title": "Build module A parser", "prompt": "Implement only the parser."},
                        ],
                    }
                ),
                "response": {},
                "command": ["claude", "-p", "<prompt>", "--model", "borg-cpu"],
                "stderr": "",
            }

    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
        claude_code_client=StructuredClaudeCodeClient(project_root=str(tmp_path)),
    )

    worker.process_next_batch()

    assert client.tables["tasks"][0]["status"] == "review_required"
    assert len([task for task in client.tables["tasks"] if task["id"] != "t1"]) == 1
    assert client.tables["project_specs"] == []
    assert any(event["event_type"] == "borg_cube_specs_storage_failed" for event in client.tables["task_events"])
    assert any(event["event_type"] == "implementation_tasks_created" for event in client.tables["task_events"])


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


def test_worker_executes_deterministic_python_command_gate(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Deterministic gate test.
status: draft
entry_node: validate
nodes:
  - id: validate
    borg_name: Validation Node
    agent: local-llm
    tasks:
      - id: python-smoke
        title: Python smoke gate
        prompt: Run a deterministic Python command.
        commands:
          - id: python-smoke
            run: python -c "print('gate-ok')"
            timeout_seconds: 10
steps:
  - id: validation
    title: Deterministic validation
    mode: sequential
    nodes:
      - validate
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task 1", "status": "queued", "workflow_id": "demo"}],
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

    worker.process_next_batch()

    command_event = next(event for event in client.tables["task_events"] if event["event_type"] == "workflow_command_succeeded")
    assert command_event["payload"]["command_id"] == "python-smoke"
    assert "gate-ok" in command_event["payload"]["stdout"]
    assert client.tables["artifacts"][0]["artifact_type"] == "workflow_command_log"
    stage_event = next(event for event in client.tables["task_events"] if event["event_type"] == "workflow_stage_completed")
    assert stage_event["payload"]["command_results"][0]["status"] == "succeeded"


def test_worker_fails_task_when_required_command_gate_fails(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    (workflows_root / "demo.yaml").write_text(
        """id: demo
title: Demo
description: Deterministic gate failure test.
status: draft
entry_node: validate
nodes:
  - id: validate
    borg_name: Validation Node
    agent: local-llm
    tasks:
      - id: failing-gate
        title: Failing gate
        command: python -c "raise SystemExit(3)"
        timeout_seconds: 10
steps:
  - id: validation
    title: Deterministic validation
    mode: sequential
    nodes:
      - validate
""",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [{"id": "t1", "title": "Task 1", "status": "queued", "workflow_id": "demo"}],
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

    worker.process_next_batch()

    assert client.tables["tasks"][0]["status"] == "failed"
    failed_event = next(event for event in client.tables["task_events"] if event["event_type"] == "workflow_command_failed")
    assert failed_event["payload"]["return_code"] == 3
    assert any(event["event_type"] == "worker_failed" for event in client.tables["task_events"])


def test_worker_pauses_sparse_project_before_llm_delegation(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    project_root = tmp_path / "firststart"
    (project_root / ".claude").mkdir(parents=True)
    (project_root / ".venv").mkdir()
    (project_root / ".idea").mkdir()
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "Continue feature work",
                    "description": "Continue implementation in the selected project.",
                    "status": "queued",
                    "local_path": str(project_root),
                }
            ],
            "task_events": [],
            "artifacts": [],
        }
    )
    worker = AgentWorker(
        task_repository=TaskRepository(client),  # type: ignore[arg-type]
        artifact_repository=ArtifactRepository(client),  # type: ignore[arg-type]
        settings=settings,
    )

    result = worker.process_task(client.tables["tasks"][0])

    assert result["status"] == "needs_input"
    assert client.tables["tasks"][0]["status"] == "needs_input"
    sparse_event = next(event for event in client.tables["task_events"] if event["event_type"] == "project_context_missing")
    assert sparse_event["payload"]["sparse"] is True
    assert sparse_event["payload"]["ignored_top_level"] == [".claude", ".idea", ".venv"]
    assert not any(event["event_type"] == "llm_request" for event in client.tables["task_events"])


def test_worker_requeues_stale_running_tasks_before_processing_queue(tmp_path: Path) -> None:
    workflows_root = tmp_path / "workflows"
    workflows_root.mkdir()
    settings = _settings(tmp_path, workflows_root)
    client = FakeSupabaseClient(
        {
            "tasks": [
                {
                    "id": "stale",
                    "title": "Stale Task",
                    "status": "running",
                    "updated_at": "2026-04-13T10:00:00Z",
                    "created_at": "2026-04-13T09:00:00Z",
                },
                {
                    "id": "fresh",
                    "title": "Fresh Task",
                    "status": "running",
                    "updated_at": "2999-01-01T10:00:00Z",
                    "created_at": "2999-01-01T09:00:00Z",
                },
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

    recovered = worker.recover_stale_running_tasks()

    statuses = {task["id"]: task["status"] for task in client.tables["tasks"]}
    assert recovered == 1
    assert statuses["stale"] == "queued"
    assert statuses["fresh"] == "running"
    recovery_event = next(event for event in client.tables["task_events"] if event["event_type"] == "worker_recovery_requeued")
    assert recovery_event["task_id"] == "stale"
    assert recovery_event["payload"]["reason"] == "stale_running_task"


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
