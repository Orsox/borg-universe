from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IssueStatus = Literal["open", "in_progress", "resolved", "closed"]

ISSUE_STATUSES: tuple[str, ...] = (
    "open",
    "in_progress",
    "resolved",
    "closed",
)

IssuePriority = Literal["low", "medium", "high", "critical"]

ISSUE_PRIORITIES: tuple[str, ...] = (
    "low",
    "medium",
    "high",
    "critical",
)


class IssueCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    project_id: str | None = None
    status: IssueStatus = "open"
    priority: IssuePriority = "medium"


class Issue(IssueCreate):
    model_config = ConfigDict(extra="allow")

    id: str
    created_at: str
    updated_at: str
