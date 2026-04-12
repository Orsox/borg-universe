from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.models.workflows import WorkflowDefinition, WorkflowStage


class WorkflowStoreError(RuntimeError):
    pass


class WorkflowStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_workflow_files(self) -> list[str]:
        if not self.root.exists():
            return []
        return [path.name for path in sorted(self.root.glob("*.y*ml")) if path.is_file()]

    def list_workflows(self) -> list[WorkflowDefinition]:
        if not self.root.exists():
            return []

        workflows: list[WorkflowDefinition] = []
        for path in sorted(self.root.glob("*.y*ml")):
            workflows.append(self._load_file(path))
        return workflows

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        for workflow in self.list_workflows():
            if workflow.id == workflow_id:
                return workflow
        return None

    def read_yaml(self, filename: str) -> str:
        path = self._resolve_file(filename)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkflowStoreError(f"Cannot read workflow {path.name}: {exc}") from exc

    def save_yaml(self, filename: str, content: str) -> WorkflowDefinition:
        path = self._resolve_file(filename, must_exist=False)
        workflow = self.validate_yaml(content, path.name)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise WorkflowStoreError(f"Cannot write workflow {path.name}: {exc}") from exc
        return workflow

    def format_workflow(self, workflow: WorkflowDefinition) -> str:
        payload = workflow.model_dump(exclude={"source_file"}, exclude_none=True)
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)

    def validate_yaml(self, content: str, filename: str = "workflow.yaml") -> WorkflowDefinition:
        try:
            raw = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise WorkflowStoreError(f"Invalid YAML in {filename}: {exc}") from exc
        return self._validate_mapping(raw, filename)

    def build_stages(self, workflow: WorkflowDefinition) -> list[WorkflowStage]:
        node_map = {node.id: node for node in workflow.nodes}
        stages: list[WorkflowStage] = []

        if workflow.steps:
            for step in workflow.steps:
                stages.append(
                    WorkflowStage(
                        title=step.title,
                        mode=step.mode,
                        nodes=[node_map[node_id] for node_id in step.nodes if node_id in node_map],
                    )
                )
            return stages

        return [
            WorkflowStage(title=node.borg_name, mode="sequential", nodes=[node])
            for node in workflow.nodes
        ]

    def _load_file(self, path: Path) -> WorkflowDefinition:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise WorkflowStoreError(f"Invalid YAML in {path.name}: {exc}") from exc
        except OSError as exc:
            raise WorkflowStoreError(f"Cannot read workflow {path.name}: {exc}") from exc

        return self._validate_mapping(raw, path.name)

    def _validate_mapping(self, raw: Any, filename: str) -> WorkflowDefinition:
        if not isinstance(raw, dict):
            raise WorkflowStoreError(f"Workflow {filename} must contain a YAML mapping.")

        payload: dict[str, Any] = {**raw, "source_file": filename}
        try:
            return WorkflowDefinition.model_validate(payload)
        except ValidationError as exc:
            raise WorkflowStoreError(f"Invalid workflow {filename}: {exc}") from exc

    def _resolve_file(self, filename: str, must_exist: bool = True) -> Path:
        name = Path(filename).name
        if name != filename or not name:
            raise WorkflowStoreError("Workflow filename must not contain path separators.")
        if not (name.endswith(".yaml") or name.endswith(".yml")):
            raise WorkflowStoreError("Workflow filename must end with .yaml or .yml.")
        path = self.root / name
        if must_exist and not path.exists():
            raise WorkflowStoreError(f"Workflow file not found: {name}")
        return path
