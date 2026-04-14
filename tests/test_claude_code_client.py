from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.services.local_llm_client import LocalLlmClient
from app.services.claude_code_client import ClaudeCodeClient, ClaudeCodeWorkspace
from app.services.orchestration_settings_store import LocalModelSettings, OrchestrationSettings


def test_claude_workspace_syncs_project_agents_and_skills(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    agents_root = project_root / "agents"
    skills_root = project_root / "skills"
    agents_root.mkdir(parents=True)
    (agents_root / "borg-queen-architect.md").write_text("---\nname: borg-queen-architect\n---\n", encoding="utf-8")
    (agents_root / "README.md").write_text("human docs only", encoding="utf-8")
    skill_root = skills_root / "borg-test-skill"
    reference_root = skill_root / "references"
    reference_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (reference_root / "example.md").write_text("example", encoding="utf-8")

    workspace = ClaudeCodeWorkspace(
        project_root=project_root,
        agents_source=agents_root,
        skills_source=skills_root,
        global_claude_root=tmp_path / "home" / ".claude",
    )

    result = workspace.ensure_project_assets()

    assert (project_root / ".claude" / "agents" / "borg-queen-architect.md").exists()
    assert not (project_root / ".claude" / "agents" / "README.md").exists()
    assert (project_root / ".claude" / "skills" / "borg-test-skill" / "SKILL.md").exists()
    assert (project_root / ".claude" / "skills" / "borg-test-skill" / "references" / "example.md").exists()
    assert result["global_agents_exists"] is False
    assert result["global_skills_exists"] is False
    assert ".claude\\agents\\borg-queen-architect.md" in result["agents"] or ".claude/agents/borg-queen-architect.md" in result["agents"]


def test_claude_code_client_invokes_cli_with_local_model_environment(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    agents_root = project_root / "agents"
    skills_root = project_root / "skills"
    agents_root.mkdir(parents=True)
    skills_root.mkdir()
    settings = _settings(tmp_path, agents_root, skills_root)
    orchestration = OrchestrationSettings(
        local_model=LocalModelSettings(
            ip_address="host.docker.internal",
            port=12345,
            api_key="lmstudio",
            model_name="borg-cpu",
        )
    )
    calls: list[dict] = []

    def runner(*args, **kwargs):
        calls.append({"args": args[0], "kwargs": kwargs})
        return subprocess.CompletedProcess(args[0], 0, stdout='{"result": "Claude delegated the task."}', stderr="")

    client = ClaudeCodeClient(
        settings=settings,
        orchestration=orchestration,
        workspace=ClaudeCodeWorkspace(
            project_root=project_root,
            agents_source=agents_root,
            skills_source=skills_root,
            global_claude_root=tmp_path / "home" / ".claude",
        ),
        runner=runner,
    )

    result = client.send_prompt("Plan the task.")

    assert result["content"] == "Claude delegated the task."
    assert calls[0]["args"][:4] == ["claude", "--bare", "--no-session-persistence", "--dangerously-skip-permissions"]
    assert calls[0]["args"][4:7] == ["-p", "Plan the task.", "--model"]
    assert calls[0]["args"][7] == "borg-cpu"
    assert calls[0]["kwargs"]["cwd"] == str(project_root)
    assert calls[0]["kwargs"]["env"]["ANTHROPIC_BASE_URL"] == "http://host.docker.internal:12345"
    assert calls[0]["kwargs"]["env"]["OPENAI_BASE_URL"] == "http://host.docker.internal:12345/v1"


def test_claude_code_client_passes_mcp_config_to_cli(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    agents_root = project_root / "agents"
    skills_root = project_root / "skills"
    agents_root.mkdir(parents=True)
    skills_root.mkdir()
    settings = _settings(tmp_path, agents_root, skills_root)
    orchestration = OrchestrationSettings(
        local_model=LocalModelSettings(
            ip_address="host.docker.internal",
            port=12345,
            api_key="lmstudio",
            model_name="borg-cpu",
        )
    )
    calls: list[dict] = []
    mcp_config_json = '{"mcpServers":{"pycharm":{"type":"http","url":"http://127.0.0.1:64769/stream"}}}'

    def runner(*args, **kwargs):
        calls.append({"args": args[0], "kwargs": kwargs})
        return subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr="")

    client = ClaudeCodeClient(
        settings=settings,
        orchestration=orchestration,
        workspace=ClaudeCodeWorkspace(
            project_root=project_root,
            agents_source=agents_root,
            skills_source=skills_root,
            global_claude_root=tmp_path / "home" / ".claude",
        ),
        runner=runner,
        mcp_config_json=mcp_config_json,
    )

    client.send_prompt("Plan the task.")

    assert calls[0]["args"][0:4] == ["claude", "--bare", "--no-session-persistence", "--dangerously-skip-permissions"]
    assert calls[0]["args"][4:6] == ["--mcp-config", mcp_config_json]
    assert calls[0]["args"][6:9] == ["-p", "Plan the task.", "--model"]
    assert calls[0]["args"][9] == "borg-cpu"


def test_claude_code_client_uses_safe_permission_mode_when_running_as_root(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    agents_root = project_root / "agents"
    skills_root = project_root / "skills"
    agents_root.mkdir(parents=True)
    skills_root.mkdir()
    settings = _settings(tmp_path, agents_root, skills_root)
    calls: list[dict] = []

    def runner(*args, **kwargs):
        calls.append({"args": args[0], "kwargs": kwargs})
        return subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr="")

    monkeypatch.setenv("CLAUDE_PERMISSION_MODE", "bypassPermissions")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    client = ClaudeCodeClient(
        settings=settings,
        orchestration=OrchestrationSettings(),
        workspace=ClaudeCodeWorkspace(
            project_root=project_root,
            agents_source=agents_root,
            skills_source=skills_root,
            global_claude_root=tmp_path / "home" / ".claude",
        ),
        runner=runner,
    )

    client.send_prompt("Plan the task.")

    assert "--dangerously-skip-permissions" not in calls[0]["args"]
    assert calls[0]["args"][0:3] == ["claude", "--bare", "--no-session-persistence"]
    assert calls[0]["args"][3:5] == ["--permission-mode", "acceptEdits"]
    assert calls[0]["args"][5:8] == ["-p", "Plan the task.", "--model"]


def test_claude_code_client_supports_configurable_permission_mode(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    agents_root = project_root / "agents"
    skills_root = project_root / "skills"
    agents_root.mkdir(parents=True)
    skills_root.mkdir()
    settings = _settings(tmp_path, agents_root, skills_root)
    calls: list[dict] = []

    def runner(*args, **kwargs):
        calls.append({"args": args[0], "kwargs": kwargs})
        return subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr="")

    monkeypatch.setenv("CLAUDE_PERMISSION_MODE", "acceptEdits")
    client = ClaudeCodeClient(
        settings=settings,
        orchestration=OrchestrationSettings(),
        workspace=ClaudeCodeWorkspace(
            project_root=project_root,
            agents_source=agents_root,
            skills_source=skills_root,
            global_claude_root=tmp_path / "home" / ".claude",
        ),
        runner=runner,
    )

    client.send_prompt("Plan the task.")

    assert calls[0]["args"][0:5] == ["claude", "--bare", "--no-session-persistence", "--permission-mode", "acceptEdits"]


def test_claude_code_client_defaults_to_ten_minute_timeout(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    agents_root = project_root / "agents"
    skills_root = project_root / "skills"
    agents_root.mkdir(parents=True)
    skills_root.mkdir()
    settings = _settings(tmp_path, agents_root, skills_root)
    orchestration = OrchestrationSettings()
    calls: list[dict] = []

    def runner(*args, **kwargs):
        calls.append({"args": args[0], "kwargs": kwargs})
        return subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr="")

    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CLAUDE_TIMEOUT_SECONDS", raising=False)
    client = ClaudeCodeClient(
        settings=settings,
        orchestration=orchestration,
        workspace=ClaudeCodeWorkspace(
            project_root=project_root,
            agents_source=agents_root,
            skills_source=skills_root,
            global_claude_root=tmp_path / "home" / ".claude",
        ),
        runner=runner,
    )

    client.send_prompt("Plan the task.")

    assert calls[0]["kwargs"]["timeout"] == 1800.0


def test_local_llm_client_defaults_to_ten_minute_timeout(monkeypatch) -> None:
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    client = LocalLlmClient(LocalModelSettings())

    assert client.timeout_seconds == 1800.0


def _settings(tmp_path: Path, agents_root: Path, skills_root: Path) -> Settings:
    return Settings(
        app_name="Borg Universe",
        app_version="0.1.0",
        environment="test",
        debug=False,
        log_level="INFO",
        borg_root=tmp_path / "BORG",
        agents_root=agents_root,
        skills_root=skills_root,
        workflows_root=tmp_path / "workflows",
        artifact_root=tmp_path / "artifacts",
        supabase_url=None,
        supabase_anon_key=None,
        supabase_service_role_key=None,
        mcp_server_url=None,
        worker_poll_interval_seconds=1.0,
        worker_batch_size=1,
    )
