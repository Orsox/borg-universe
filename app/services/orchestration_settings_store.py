from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


AGENT_SYSTEMS = ("claude_code", "codex", "local_model", "custom")


class AgentSelectionSettings(BaseModel):
    agent_system: Literal["claude_code", "cloud_code", "codex", "local_model", "custom"] = "codex"
    agent_name: str | None = None
    notes: str | None = None

    @field_validator("agent_system", mode="before")
    @classmethod
    def normalize_agent_system(cls, value: str) -> str:
        if value == "cloud_code":
            return "claude_code"
        return value


class LocalModelSettings(BaseModel):
    ip_address: str = "127.0.0.1"
    port: int = Field(default=11434, ge=1, le=65535)
    api_key: str | None = None
    model_name: str | None = None

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address_or_hostname(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Local model host is required")
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            pass
        if len(value) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", value):
            raise ValueError("Local model host must be an IP address or hostname")
        labels = value.split(".")
        if any(not label or label.startswith("-") or label.endswith("-") or len(label) > 63 for label in labels):
            raise ValueError("Local model host must be an IP address or hostname")
        return value


class ExecutionSettings(BaseModel):
    max_parallel_tasks: int = Field(default=1, ge=1, le=32)


class OrchestrationSettings(BaseModel):
    agent_selection: AgentSelectionSettings = Field(default_factory=AgentSelectionSettings)
    local_model: LocalModelSettings = Field(default_factory=LocalModelSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    updated_at: str | None = None


class OrchestrationSettingsStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "config" / "orchestration.json"

    def load(self) -> OrchestrationSettings:
        if not self.path.exists():
            return OrchestrationSettings()

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read orchestration settings: {exc}") from exc

        try:
            return OrchestrationSettings.model_validate(raw)
        except ValidationError as exc:
            raise RuntimeError(f"Invalid orchestration settings: {exc}") from exc

    def save(
        self,
        *,
        agent_selection: AgentSelectionSettings | None = None,
        local_model: LocalModelSettings | None = None,
        execution: ExecutionSettings | None = None,
    ) -> OrchestrationSettings:
        current = self.load()
        payload = OrchestrationSettings(
            agent_selection=agent_selection or current.agent_selection,
            local_model=local_model or current.local_model,
            execution=execution or current.execution,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload.model_dump(mode="json"), indent=2), encoding="utf-8")
        return payload
