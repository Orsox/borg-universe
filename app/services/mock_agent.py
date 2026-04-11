from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings
from app.db.repositories import TaskRepository


class MockAgentError(RuntimeError):
    pass


def run_mock_agent(task_id: str, task_repo: TaskRepository, settings: Settings) -> dict[str, Any]:
    task = task_repo.get_task(task_id)
    if not task:
        raise MockAgentError(f"Task not found: {task_id}")
    if not settings.mcp_server_url:
        raise MockAgentError("MCP_SERVER_URL is not configured")

    agent_name = task.get("assigned_agent") or "mock-agent"
    skill_name = task.get("assigned_skill")
    arguments = {
        "query": task.get("topic") or task.get("title"),
        "platform": task.get("target_platform"),
        "peripheral": task.get("topic"),
        "limit": 5,
    }
    lookup = _call_mcp(
        settings.mcp_server_url,
        "project.search",
        {
            "agent_name": agent_name,
            "skill_name": skill_name,
            "task_id": task_id,
            "project_id": "local",
            "arguments": arguments,
        },
    )

    result_count = int(lookup.get("result_count", 0))
    task_repo.add_event(
        task_id,
        "project_lookup_completed" if result_count else "project_lookup_empty",
        f"Mock agent project lookup returned {result_count} result(s).",
        {
            "agent_name": agent_name,
            "skill_name": skill_name,
            "tool": "project.search",
            "result_count": result_count,
        },
    )
    task_repo.add_event(
        task_id,
        "mock_agent_completed",
        "Mock agent completed Phase 6 end-to-end verification.",
        {"result_count": result_count},
    )
    return {"task_id": task_id, "agent_name": agent_name, "lookup": lookup}


def _call_mcp(base_url: str, tool_name: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/tools/{tool_name}/call",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise MockAgentError(details) from exc
    except URLError as exc:
        raise MockAgentError(str(exc.reason)) from exc
