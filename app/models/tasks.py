from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal[
    "draft",
    "queued",
    "running",
    "needs_input",
    "review_required",
    "done",
    "failed",
    "cancelled",
]

TASK_STATUSES: tuple[str, ...] = (
    "draft",
    "queued",
    "running",
    "needs_input",
    "review_required",
    "done",
    "failed",
    "cancelled",
)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    target_platform: str | None = None
    target_mcu: str | None = None
    board: str | None = None
    topic: str | None = None
    requested_by: str | None = None
    assigned_agent: str | None = None
    assigned_skill: str | None = None


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class Task(TaskCreate):
    model_config = ConfigDict(extra="allow")

    id: str
    status: TaskStatus
    created_at: str
    updated_at: str


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    task_id: str
    event_type: str
    message: str
    payload: dict
    created_at: str
