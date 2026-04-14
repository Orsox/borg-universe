from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from mcp_server.tools import knowledge_tools, task_tools


ToolHandler = Callable[[dict[str, Any]], list[dict[str, Any]] | dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    write: bool = False


class ToolRegistry:
    def __init__(self, client: SupabaseRestClient, tools: dict[str, ToolDefinition]) -> None:
        self.client = client
        self.tools = tools

    def list_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "write": tool.write,
            }
            for tool in self.tools.values()
        ]

    def call(
        self,
        tool_name: str,
        *,
        arguments: dict[str, Any],
        agent_name: str | None,
        skill_name: str | None,
        task_id: str | None,
        project_id: str | None,
    ) -> dict[str, Any]:
        if tool_name not in self.tools:
            raise KeyError(f"Unknown MCP tool: {tool_name}")

        tool = self.tools[tool_name]
        query = {
            "arguments": arguments,
            "agent_name": agent_name,
            "skill_name": skill_name,
            "task_id": task_id,
            "project_id": project_id,
        }
        try:
            result = tool.handler(arguments)
            result_count = _result_count(result)
            self._audit(
                tool_name,
                query,
                result_count,
                agent_name=agent_name,
                skill_name=skill_name,
                task_id=task_id,
                project_id=project_id,
                success=True,
                error=None,
            )
            return {"tool": tool_name, "result_count": result_count, "result": result}
        except Exception as exc:
            self._audit(
                tool_name,
                query,
                0,
                agent_name=agent_name,
                skill_name=skill_name,
                task_id=task_id,
                project_id=project_id,
                success=False,
                error=str(exc),
            )
            raise

    def _audit(
        self,
        tool_name: str,
        query: dict[str, Any],
        result_count: int,
        *,
        agent_name: str | None,
        skill_name: str | None,
        task_id: str | None,
        project_id: str | None,
        success: bool,
        error: str | None,
    ) -> None:
        body = {
            "tool_name": tool_name,
            "query": query,
            "result_count": result_count,
            "agent_name": agent_name,
            "skill_name": skill_name,
            "task_id": task_id,
            "project_id": project_id,
            "success": success,
            "error": error,
        }
        self.client.request("POST", "mcp_access_logs", body=body, prefer="return=minimal")


def build_registry(client: SupabaseRestClient) -> ToolRegistry:
    tools = {
        "project.search": ToolDefinition(
            name="project.search",
            description="Search project metadata, borg-cube specs, tasks, knowledge, rules, and examples.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "platform": {"type": "string"},
                    "peripheral": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
            handler=lambda args: knowledge_tools.project_search(client, args),
        ),
        "knowledge.search": ToolDefinition(
            name="knowledge.search",
            description="Search knowledge entries by platform, MCU family, peripheral, tag, or text query.",
            input_schema=_search_schema(["platform", "mcu_family", "peripheral", "tags", "query", "limit"]),
            handler=lambda args: knowledge_tools.search_table(
                client,
                "knowledge_entries",
                args,
                text_columns=("title", "content", "source"),
                filter_columns=("platform", "mcu_family", "peripheral", "tags"),
            ),
        ),
        "knowledge.get_entry": ToolDefinition(
            name="knowledge.get_entry",
            description="Fetch a single knowledge entry by id.",
            input_schema={"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
            handler=lambda args: knowledge_tools.get_item(client, "knowledge_entries", args),
        ),
        "rules.search": ToolDefinition(
            name="rules.search",
            description="Search development rules by scope, severity, applies_to, or text query.",
            input_schema=_search_schema(["scope", "severity", "applies_to", "query", "limit"]),
            handler=lambda args: knowledge_tools.search_table(
                client,
                "rules",
                args,
                text_columns=("name", "rule_text"),
                filter_columns=("scope", "severity", "applies_to"),
            ),
        ),
        "examples.search": ToolDefinition(
            name="examples.search",
            description="Search code examples by platform, framework, peripheral, tag, or text query.",
            input_schema=_search_schema(["platform", "framework", "peripheral", "tags", "query", "limit"]),
            handler=lambda args: knowledge_tools.search_table(
                client,
                "code_examples",
                args,
                text_columns=("title", "code", "explanation"),
                filter_columns=("platform", "framework", "peripheral", "tags"),
            ),
        ),
        "tasks.get": ToolDefinition(
            name="tasks.get",
            description="Fetch a task and its event history by id.",
            input_schema={"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
            handler=lambda args: task_tools.get_task(client, args),
        ),
        "tasks.add_event": ToolDefinition(
            name="tasks.add_event",
            description="Append an event to a task.",
            input_schema={
                "type": "object",
                "required": ["task_id", "event_type", "message"],
                "properties": {
                    "task_id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "message": {"type": "string"},
                    "payload": {"type": "object"},
                },
            },
            handler=lambda args: task_tools.add_event(client, args),
            write=True,
        ),
        "tasks.request_input": ToolDefinition(
            name="tasks.request_input",
            description="Mark a task as needing input and append a request event.",
            input_schema={
                "type": "object",
                "required": ["task_id", "message"],
                "properties": {"task_id": {"type": "string"}, "message": {"type": "string"}, "payload": {"type": "object"}},
            },
            handler=lambda args: task_tools.request_input(client, args),
            write=True,
        ),
        "artifacts.create": ToolDefinition(
            name="artifacts.create",
            description="Record an artifact placeholder as a task event for Phase 5.",
            input_schema={
                "type": "object",
                "required": ["task_id", "artifact_type", "path_or_storage_key"],
                "properties": {
                    "task_id": {"type": "string"},
                    "artifact_type": {"type": "string"},
                    "path_or_storage_key": {"type": "string"},
                    "checksum": {"type": "string"},
                },
            },
            handler=lambda args: task_tools.create_artifact_event(client, args),
            write=True,
        ),
        "agents.list": ToolDefinition(
            name="agents.list",
            description="List registered agents when the agents table exists.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: knowledge_tools.optional_table_list(client, "agents"),
        ),
        "skills.list": ToolDefinition(
            name="skills.list",
            description="List registered skills when the skills table exists.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: knowledge_tools.optional_table_list(client, "skills"),
        ),
    }
    return ToolRegistry(client, tools)


def _search_schema(keys: list[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key in keys:
        if key == "limit":
            properties[key] = {"type": "integer", "minimum": 1, "maximum": 50}
        else:
            properties[key] = {"type": "string"}
    return {"type": "object", "properties": properties}


def _result_count(result: list[dict[str, Any]] | dict[str, Any]) -> int:
    if isinstance(result, list):
        return len(result)
    if "items" in result and isinstance(result["items"], list):
        return len(result["items"])
    nested_count = sum(len(value) for value in result.values() if isinstance(value, list))
    if nested_count:
        return nested_count
    return 1
