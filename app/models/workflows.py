from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


WorkflowMode = Literal["sequential", "parallel"]
WorkflowStatus = Literal["draft", "queued", "running", "needs_input", "review_required", "done", "failed"]


class WorkflowCommand(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    run: str = Field(min_length=1)
    working_dir: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    allow_failure: bool = False
    only_if_path_exists: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class WorkflowTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    prompt: str = ""
    status: WorkflowStatus = "draft"
    depends_on: list[str] = Field(default_factory=list)
    command: str | WorkflowCommand | None = None
    commands: list[str | WorkflowCommand] = Field(default_factory=list)
    working_dir: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    allow_failure: bool = False
    only_if_path_exists: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    borg_name: str = Field(min_length=1)
    role: str = "agent"
    agent: str | None = None
    subagents: list[str] = Field(default_factory=list)
    tasks: list[WorkflowTask] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    mode: WorkflowMode = "sequential"
    nodes: list[str] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    status: WorkflowStatus = "draft"
    entry_node: str
    nodes: list[WorkflowNode] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)
    source_file: str | None = None


class WorkflowStage(BaseModel):
    title: str
    mode: WorkflowMode
    nodes: list[WorkflowNode]
