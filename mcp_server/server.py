from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.db.supabase_client import SupabaseRestClient, SupabaseRestError
from mcp_server.tools.registry import ToolRegistry, build_registry


class ToolCallRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)
    agent_name: str | None = None
    skill_name: str | None = None
    task_id: str | None = None
    project_id: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Borg Universe MCP Server", version="0.1.0")

    @app.get("/health", tags=["system"])
    async def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
        return {
            "status": "ok",
            "service": "borg-universe-mcp",
            "supabase_configured": settings.supabase_configured,
        }

    @app.get("/tools", tags=["mcp"])
    async def list_tools(registry: Annotated[ToolRegistry, Depends(get_registry)]) -> list[dict]:
        return registry.list_schemas()

    @app.post("/tools/{tool_name}/call", tags=["mcp"])
    async def call_tool(
        tool_name: str,
        request: ToolCallRequest,
        registry: Annotated[ToolRegistry, Depends(get_registry)],
    ) -> dict:
        try:
            return registry.call(
                tool_name,
                arguments=request.arguments,
                agent_name=request.agent_name,
                skill_name=request.skill_name,
                task_id=request.task_id,
                project_id=request.project_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except SupabaseRestError as exc:
            code = exc.status_code or status.HTTP_503_SERVICE_UNAVAILABLE
            if code >= 500:
                code = status.HTTP_503_SERVICE_UNAVAILABLE
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    return app


def get_registry(settings: Annotated[Settings, Depends(get_settings)]) -> ToolRegistry:
    return build_registry(SupabaseRestClient(settings))


app = create_app()
