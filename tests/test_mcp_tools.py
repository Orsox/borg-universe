from __future__ import annotations

import pytest

from mcp_server.tools.knowledge_tools import project_search, search_table
from mcp_server.tools.registry import build_registry
from mcp_server.tools.task_tools import request_input
from tests.fakes import FakeSupabaseClient


def test_search_table_clamps_limit_and_filters_text() -> None:
    client = FakeSupabaseClient(
        {
            "knowledge_entries": [
                {"id": "k1", "title": "SPI init", "content": "HAL setup", "platform": "STM32", "tags": ["spi"]},
                {"id": "k2", "title": "UART init", "content": "HAL setup", "platform": "STM32", "tags": ["uart"]},
            ]
        }
    )

    rows = search_table(
        client,  # type: ignore[arg-type]
        "knowledge_entries",
        {"platform": "STM32", "query": "SPI", "limit": 500},
        text_columns=("title", "content"),
        filter_columns=("platform", "tags"),
    )

    assert [row["id"] for row in rows] == ["k1"]
    assert client.calls[0]["query"]["limit"] == "50"


def test_project_search_aggregates_context_sources() -> None:
    client = FakeSupabaseClient(
        {
            "knowledge_entries": [{"id": "k1", "title": "SPI", "content": "SPI", "platform": "STM32"}],
            "rules": [{"id": "r1", "name": "Rule", "rule_text": "SPI"}],
            "code_examples": [{"id": "e1", "title": "Example", "code": "SPI", "platform": "STM32"}],
            "tasks": [{"id": "t1", "title": "SPI task", "description": "", "topic": "SPI"}],
            "projects": [{"id": "p1", "name": "SPI Project", "description": "", "project_directory": "", "active": True}],
            "project_specs": [{"id": "s1", "spec_path": "borg-cube.md", "title": "SPI Spec", "content": "SPI module"}],
        }
    )

    result = project_search(client, {"platform": "STM32", "query": "SPI", "limit": 5})  # type: ignore[arg-type]

    assert {key: len(value) for key, value in result.items()} == {
        "projects": 1,
        "knowledge": 1,
        "rules": 1,
        "examples": 1,
        "tasks": 1,
        "specs": 1,
    }


def test_registry_audits_successful_tool_call() -> None:
    client = FakeSupabaseClient(
        {
            "knowledge_entries": [],
            "rules": [],
            "code_examples": [],
            "tasks": [],
            "mcp_access_logs": [],
        }
    )
    registry = build_registry(client)  # type: ignore[arg-type]

    result = registry.call(
        "project.search",
        arguments={"query": "none"},
        agent_name="agent",
        skill_name="skill",
        task_id="t1",
        project_id="local",
    )

    assert result["tool"] == "project.search"
    assert client.tables["mcp_access_logs"][0]["success"] is True
    assert client.tables["mcp_access_logs"][0]["agent_name"] == "agent"


def test_registry_audits_failed_tool_call() -> None:
    client = FakeSupabaseClient({"mcp_access_logs": []})
    registry = build_registry(client)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        registry.call(
            "knowledge.get_entry",
            arguments={},
            agent_name="agent",
            skill_name=None,
            task_id=None,
            project_id=None,
        )

    assert client.tables["mcp_access_logs"][0]["success"] is False
    assert "Missing required argument" in client.tables["mcp_access_logs"][0]["error"]


def test_request_input_changes_status_and_adds_event() -> None:
    client = FakeSupabaseClient(
        {"tasks": [{"id": "t1", "status": "running"}], "task_events": []}
    )

    event = request_input(client, {"task_id": "t1", "message": "Need board"})  # type: ignore[arg-type]

    assert client.tables["tasks"][0]["status"] == "needs_input"
    assert event["event_type"] == "input_requested"
