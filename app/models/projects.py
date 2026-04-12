from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ProjectType = Literal["stm", "nordic", "python"]

PROJECT_TYPES: tuple[dict[str, str], ...] = (
    {"value": "stm", "label": "STM"},
    {"value": "nordic", "label": "Nordic"},
    {"value": "python", "label": "Python"},
)


class ProjectCreate(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    project_type: ProjectType
    project_directory: str = ""
    pycharm_mcp_enabled: bool = False
    pycharm_mcp_sse_url: str | None = None
    pycharm_mcp_stream_url: str | None = None
    default_platform: str | None = None
    default_mcu: str | None = None
    default_board: str | None = None
    default_topic: str | None = None
    active: bool = True
