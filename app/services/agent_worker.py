from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings
from app.db.repositories import ArtifactRepository, ProjectSpecRepository, TaskRepository
from app.db.supabase_client import SupabaseRestError
from app.services.claude_code_client import ClaudeCodeClient, ClaudeCodeClientError, ClaudeCodeWorkspace
from app.models.workflows import WorkflowCommand, WorkflowDefinition, WorkflowNode, WorkflowTask
from app.models.tasks import TaskCreate
from app.services.local_llm_client import LocalLlmClient, LocalLlmClientError
from app.services.orchestration_settings_store import OrchestrationSettings
from app.services.orchestration_settings_store import OrchestrationSettingsStore
from app.services.workflow_store import WorkflowStore, WorkflowStoreError

logger = logging.getLogger(__name__)


class AgentWorker:
    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        artifact_repository: ArtifactRepository,
        settings: Settings,
        workflow_store: WorkflowStore | None = None,
        orchestration_store: OrchestrationSettingsStore | None = None,
        local_llm_client: Any | None = None,
        claude_code_client: Any | None = None,
    ) -> None:
        self.task_repository = task_repository
        self.artifact_repository = artifact_repository
        self.settings = settings
        self.workflow_store = workflow_store or WorkflowStore(settings.workflows_root)
        self.orchestration_store = orchestration_store or OrchestrationSettingsStore(settings.borg_root)
        self.local_llm_client = local_llm_client
        self.claude_code_client = claude_code_client

    def process_next_batch(self) -> int:
        self.recover_stale_running_tasks()
        tasks = self.task_repository.list_by_status("queued", self._queue_parallelism())
        for task in tasks:
            self.process_task(task)
        return len(tasks)

    def recover_stale_running_tasks(self) -> int:
        timeout_seconds = float(getattr(self.settings, "worker_running_task_timeout_seconds", 900.0))
        if timeout_seconds <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
        limit = max(self._queue_parallelism(), self.settings.worker_batch_size, 1)
        tasks = self.task_repository.list_stale_running(cutoff_iso, limit)
        recovered = 0
        for task in tasks:
            task_id = str(task["id"])
            self.task_repository.add_event(
                task_id,
                "worker_recovery_requeued",
                "Worker recovered a stale running task and returned it to the queue.",
                {
                    "previous_status": task.get("status"),
                    "updated_at": task.get("updated_at"),
                    "cutoff": cutoff_iso,
                    "timeout_seconds": timeout_seconds,
                    "reason": "stale_running_task",
                },
            )
            if self.task_repository.update_status(task_id, "queued"):
                recovered += 1
        return recovered

    def process_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["id"]
        agent_name = task.get("assigned_agent") or "mock-agent"
        skill_name = task.get("assigned_skill")
        initial_events: list[dict[str, Any]] = []
        try:
            initial_events = self.task_repository.list_events(task_id)
            resume_context = self._latest_workflow_resume(initial_events)
            if resume_context:
                print(f"[WORKER] picked up post-review continuation for task {task_id}")
            else:
                print(f"[WORKER] picked up task {task_id}")
            self.task_repository.update_status(task_id, "running")
            self.task_repository.add_event(
                task_id,
                "agent_started",
                f"Worker assigned task to {agent_name}.",
                {"agent_name": agent_name, "skill_name": skill_name, "workflow_id": task.get("workflow_id")},
            )
            if self._is_implementation_task(task):
                result = self._run_implementation_task(task)
                self.task_repository.update_status(task_id, "done")
                return result
            if self._is_implementation_task_without_codeword(task):
                self.task_repository.add_event(
                    task_id,
                    "implementation_codeword_missing",
                    "Implementation task is missing the required <nano-implant> codeword.",
                    {"agent_name": agent_name},
                )
                self.task_repository.update_status(task_id, "needs_input")
                return {"task_id": task_id, "status": "needs_input", "reason": "missing_nano_implant"}
            if not resume_context:
                sparse_project = self._maybe_pause_for_sparse_project(task)
                if sparse_project:
                    return sparse_project
            if resume_context:
                review_context = self._latest_review_context(initial_events)
                print(f"[WORKFLOW] Continuing after review with input: {review_context.get('notes') if review_context else 'None'}")
                self.task_repository.add_event(
                    task_id,
                    "workflow_resume_detected",
                    "Worker detected a confirmed review and will resume the workflow.",
                    {
                        "resume_stage_index": resume_context.get("resume_stage_index", 1),
                        "has_review_notes": bool(review_context and review_context.get("notes")),
                        "review_notes_length": len(str((review_context or {}).get("notes") or "")),
                        "has_llm_output": bool(review_context and review_context.get("output")),
                    },
                )
                llm_plan = self._run_review_resume_llm_processing(task, review_context, resume_context)
                self.task_repository.add_event(
                    task_id,
                    "implementation_started",
                    "Review was confirmed; implementation resumes at the next workflow level.",
                    {
                        **resume_context,
                        "review_notes_forwarded_to_llm": bool(review_context and review_context.get("notes")),
                        "llm_resume_summary": llm_plan.get("summary"),
                    },
                )
            else:
                llm_plan = self._run_local_llm_processing(task)
            workflow_result: dict[str, Any] = {
                "paused_for_review": False,
                "completed_all_stages": False,
                "uses_explicit_review": False,
                "executed_stage_count": 0,
            }
            if task.get("workflow_id"):
                self.task_repository.add_event(
                    task_id,
                    "workflow_started",
                    "Worker started the selected workflow after local LLM processing.",
                    {"workflow_id": task.get("workflow_id"), "agent_name": agent_name, "llm_plan": llm_plan},
                )
                workflow_result = self._run_workflow(
                    task,
                    agent_name,
                    llm_plan,
                    stage_index=resume_context.get("resume_stage_index", 0) if resume_context else 0,
                )
            if resume_context:
                resumed_stage_index = resume_context.get("resume_stage_index", 0)
                self.task_repository.add_event(
                    task_id,
                    "post_review_stage_execution",
                    "Worker evaluated post-review workflow execution.",
                    {
                        "resume_stage_index": resumed_stage_index,
                        "executed_stage_count": workflow_result.get("executed_stage_count", 0),
                        "completed_all_stages": workflow_result.get("completed_all_stages", False),
                    },
                )
                if int(workflow_result.get("executed_stage_count", 0)) <= 0:
                    message = "Premature completion blocked: no post-review execution ran after review."
                    self.task_repository.add_event(
                        task_id,
                        "workflow_premature_completion_blocked",
                        message,
                        {
                            "resume_stage_index": resumed_stage_index,
                            "workflow_id": task.get("workflow_id"),
                        },
                    )
                    self.task_repository.update_status(task_id, "failed")
                    raise RuntimeError(message)
            self.task_repository.add_event(
                task_id,
                "project_lookup_started",
                "Worker started mandatory Supabase project context lookup.",
                {"tool": "project.search", "agent_name": agent_name, "skill_name": skill_name},
            )

            lookup = self._project_lookup(task, agent_name, skill_name)
            result_count = int(lookup.get("result_count", 0))
            if result_count == 0 and self.settings.mcp_server_url:
                self.task_repository.add_event(
                    task_id,
                    "project_lookup_empty",
                    "Mandatory Supabase project context lookup returned no results.",
                    {"tool": "project.search", "result_count": 0},
                )
                self.task_repository.add_event(
                    task_id,
                    "input_requested",
                    "No project context was found. Add knowledge, rules, examples, or clarify the task.",
                    {"reason": "empty_project_lookup"},
                )
                self.task_repository.update_status(task_id, "needs_input")
                return {"task_id": task_id, "status": "needs_input", "result_count": 0}

            self.task_repository.add_event(
                task_id,
                "project_lookup_completed",
                f"Mandatory Supabase project context lookup returned {result_count} result(s).",
                {"tool": "project.search", "result_count": result_count},
            )
            summary = self._build_result_summary(task, agent_name, skill_name, lookup)
            artifact = self.artifact_repository.create_artifact(
                task_id=task_id,
                artifact_type="agent_result",
                path_or_storage_key=f"supabase://task_events/{task_id}/agent_result_ready",
            )
            self.task_repository.add_event(
                task_id,
                "agent_result_ready",
                summary,
                {
                    "agent_name": agent_name,
                    "skill_name": skill_name,
                    "artifact_id": artifact["id"],
                    "result_count": result_count,
                },
            )
            self.task_repository.add_event(
                task_id,
                "no_file_changes_applied",
                "No file changes were applied during this run; the worker completed analysis, workflow traversal, and project lookup only.",
                {
                    "applied": False,
                    "workflow_id": task.get("workflow_id"),
                    "project_id": task.get("project_id"),
                    "local_path": task.get("local_path"),
                    "pycharm_mcp_enabled": bool(task.get("pycharm_mcp_enabled")),
                },
            )
            if workflow_result.get("paused_for_review"):
                self.task_repository.add_event(
                    task_id,
                    "review_required",
                    "Worker paused at an explicit human review checkpoint.",
                    {
                        "artifact_id": artifact["id"],
                        "review_stage_index": workflow_result.get("review_stage_index"),
                        "review_stage_id": workflow_result.get("review_stage_id"),
                        "next_stage_index": workflow_result.get("next_stage_index"),
                    },
                )
                self.task_repository.update_status(task_id, "review_required")
                return {"task_id": task_id, "status": "review_required", "result_count": result_count}

            if workflow_result.get("uses_explicit_review") and workflow_result.get("completed_all_stages"):
                print("[WORKFLOW] marking task as done")
                self.task_repository.update_status(task_id, "done")
                return {"task_id": task_id, "status": "done", "result_count": result_count}

            self.task_repository.add_event(
                task_id,
                "review_required",
                "Worker completed controlled agentic processing without applying file changes and marked the result for review.",
                {"artifact_id": artifact["id"]},
            )
            self.task_repository.update_status(task_id, "review_required")
            return {"task_id": task_id, "status": "review_required", "result_count": result_count}
        except Exception as exc:
            logger.exception("Worker failed while processing task %s", task_id)
            if _is_file_access_blocker_error(exc):
                self.task_repository.add_event(
                    task_id,
                    "worker_file_access_blocked",
                    str(exc),
                    {"agent_name": agent_name, "skill_name": skill_name, "guard": "file_access_blocker"},
                )
                self.task_repository.update_status(task_id, "needs_input")
                return {"task_id": task_id, "status": "needs_input", "error": str(exc), "reason": "file_access_blocker"}
            if _is_temporary_infrastructure_error(exc):
                retry_events = [
                    event
                    for event in (initial_events or self.task_repository.list_events(task_id))
                    if event.get("event_type") == "worker_temporary_failure_requeued"
                ]
                attempt = len(retry_events) + 1
                max_retries = max(0, int(getattr(self.settings, "worker_temporary_failure_max_retries", 3)))
                if attempt > max_retries:
                    self.task_repository.add_event(
                        task_id,
                        "worker_temporary_failure_exhausted",
                        str(exc),
                        {
                            "agent_name": agent_name,
                            "skill_name": skill_name,
                            "attempt": attempt,
                            "max_retries": max_retries,
                            "guard": "temporary_failure_retry_budget",
                        },
                    )
                    self.task_repository.update_status(task_id, "failed")
                    return {
                        "task_id": task_id,
                        "status": "failed",
                        "error": str(exc),
                        "retry": False,
                        "attempt": attempt,
                        "max_retries": max_retries,
                    }
                self.task_repository.add_event(
                    task_id,
                    "worker_temporary_failure_requeued",
                    str(exc),
                    {
                        "agent_name": agent_name,
                        "skill_name": skill_name,
                        "attempt": attempt,
                        "max_retries": max_retries,
                    },
                )
                self.task_repository.update_status(task_id, "queued")
                return {
                    "task_id": task_id,
                    "status": "queued",
                    "error": str(exc),
                    "retry": True,
                    "attempt": attempt,
                    "max_retries": max_retries,
                }
            self.task_repository.add_event(
                task_id,
                "worker_failed",
                str(exc),
                {"agent_name": agent_name, "skill_name": skill_name},
            )
            self.task_repository.update_status(task_id, "failed")
            return {"task_id": task_id, "status": "failed", "error": str(exc)}

    def _queue_parallelism(self) -> int:
        try:
            return self.orchestration_store.load().execution.max_parallel_tasks
        except RuntimeError:
            return self.settings.worker_batch_size

    def _run_local_llm_processing(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["id"]
        review_context = self._latest_review_context(self.task_repository.list_events(task_id))
        orchestration = self.orchestration_store.load()
        if self._should_use_claude_code(orchestration):
            return self._run_claude_code_processing(task, review_context, orchestration)

        self.task_repository.add_event(
            task_id,
            "llm_processing_started",
            "Local LLM processing started before workflow node selection.",
            {
                "local_path": task.get("local_path"),
                "pycharm_mcp_enabled": bool(task.get("pycharm_mcp_enabled")),
                "review_context": review_context,
            },
        )

        client = self.local_llm_client or LocalLlmClient(orchestration.local_model)
        prompts = [
            self._llm_planning_prompt(task, review_context),
            "Parse the previous answer into concrete next steps. Return compact JSON if possible.",
            "Select the first workflow node to execute after planning. Return JSON with first_node_id and summary.",
        ]
        previous_output = ""
        plan: dict[str, Any] = {"summary": "", "first_node_id": None, "iterations": []}
        for index, prompt in enumerate(prompts, start=1):
            composed_prompt = f"{prompt}\n\nPrevious output:\n{previous_output}" if previous_output else prompt
            composed_prompt = self._prepare_prompt_with_deep_guard(
                task_id,
                composed_prompt,
                provider="local",
                phase="planning",
                iteration=index,
            )
            self.task_repository.add_event(
                task_id,
                "llm_request",
                "LLM request sent for human review.",
                {
                    "iteration": index,
                    "provider": "local",
                    "model": orchestration.local_model.model_name,
                    "prompt": composed_prompt,
                },
            )
            try:
                result = client.send_prompt(composed_prompt)
            except LocalLlmClientError as exc:
                self.task_repository.add_event(
                    task_id,
                    "llm_processing_failed",
                    "Local LLM processing failed.",
                    {"iteration": index, "error": str(exc)},
                )
                raise RuntimeError(f"Local LLM processing failed: {exc}") from exc

            output = str(result.get("content", "")).strip()
            _raise_if_tool_approval_loop(output)
            previous_output = output
            parsed = _parse_json_object(output)
            if parsed.get("first_node_id"):
                plan["first_node_id"] = str(parsed["first_node_id"])
            if parsed.get("summary"):
                plan["summary"] = str(parsed["summary"])
            plan["iterations"].append({"iteration": index, "output": output})
            self.task_repository.add_event(
                task_id,
                "llm_response",
                "LLM response received for human review.",
                {
                    "iteration": index,
                    "provider": "local",
                    "model": orchestration.local_model.model_name,
                    "response": output,
                    "parsed": parsed,
                },
            )
            self.task_repository.add_event(
                task_id,
                "llm_iteration_completed",
                "Local LLM iteration completed.",
                {
                    "iteration": index,
                    "prompt": composed_prompt,
                    "output": output,
                    "parsed": parsed,
                },
            )

        if not plan["summary"]:
            plan["summary"] = previous_output[:500]
        self.task_repository.add_event(
            task_id,
            "llm_processing_completed",
            "Local LLM processing completed; workflow node selection can begin.",
            {
                "summary": plan["summary"],
                "first_node_id": plan["first_node_id"],
                "human_review_text": self._render_llm_human_review_text(plan),
            },
        )
        return plan

    def _run_review_resume_llm_processing(
        self,
        task: dict[str, Any],
        review_context: dict[str, str] | None,
        resume_context: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = task["id"]
        stage_index = int(resume_context.get("resume_stage_index", 1))
        orchestration = self.orchestration_store.load()
        if self._should_use_claude_code(orchestration):
            return self._run_claude_code_processing(
                task,
                review_context,
                orchestration,
                phase="review_resume",
                resume_context=resume_context,
            )

        self.task_repository.add_event(
            task_id,
            "llm_resume_processing_started",
            "Review notes are being sent to the local LLM before workflow execution resumes.",
            {
                "resume_stage_index": stage_index,
                "local_path": task.get("local_path"),
                "pycharm_mcp_enabled": bool(task.get("pycharm_mcp_enabled")),
                "review_context": review_context,
            },
        )

        client = self.local_llm_client or LocalLlmClient(orchestration.local_model)
        prompt = self._llm_review_resume_prompt(task, review_context, stage_index)
        prompt = self._prepare_prompt_with_deep_guard(
            task_id,
            prompt,
            provider="local",
            phase="review_resume",
            iteration=1,
        )
        print(f"[LLM] executing continuation with review input for task {task_id}")
        self.task_repository.add_event(
            task_id,
            "llm_request",
            "LLM request sent with confirmed review notes before workflow resume.",
            {
                "iteration": 1,
                "phase": "review_resume",
                "provider": "local",
                "model": orchestration.local_model.model_name,
                "prompt": prompt,
            },
        )
        try:
            result = client.send_prompt(prompt)
        except LocalLlmClientError as exc:
            self.task_repository.add_event(
                task_id,
                "llm_resume_processing_failed",
                "Local LLM resume processing failed before workflow execution.",
                {"resume_stage_index": stage_index, "error": str(exc)},
            )
            raise RuntimeError(f"Local LLM resume processing failed: {exc}") from exc

        output = str(result.get("content", "")).strip()
        _raise_if_tool_approval_loop(output)
        parsed = _parse_json_object(output)
        summary = str(parsed.get("summary") or output[:500]).strip()
        plan = {
            "summary": summary,
            "first_node_id": None,
            "iterations": [{"iteration": 1, "phase": "review_resume", "output": output}],
            "review_context": review_context,
            "resume_stage_index": stage_index,
        }
        self.task_repository.add_event(
            task_id,
            "llm_response",
            "LLM response received for confirmed review notes.",
            {
                "iteration": 1,
                "phase": "review_resume",
                "provider": "local",
                "model": orchestration.local_model.model_name,
                "response": output,
                "parsed": parsed,
            },
        )
        self.task_repository.add_event(
            task_id,
            "llm_iteration_completed",
            "Local LLM resume iteration completed.",
            {
                "iteration": 1,
                "phase": "review_resume",
                "prompt": prompt,
                "output": output,
                "parsed": parsed,
            },
        )
        self.task_repository.add_event(
            task_id,
            "llm_resume_processing_completed",
            "Local LLM processed confirmed review notes; workflow resume can begin.",
            {
                "summary": summary,
                "resume_stage_index": stage_index,
                "human_review_text": self._render_llm_human_review_text(plan),
            },
        )
        return plan

    def _should_use_claude_code(self, orchestration: OrchestrationSettings) -> bool:
        if self.local_llm_client is not None:
            return False
        if self.claude_code_client is not None:
            return True
        system = orchestration.agent_selection.agent_system
        model_name = (orchestration.local_model.model_name or "").strip().lower()
        agent_name = (orchestration.agent_selection.agent_name or "").strip().lower()
        return system in {"claude_code", "cloud_code"} or model_name == "borg-cpu" or agent_name == "borg-cpu"

    def _is_implementation_task(self, task: dict[str, Any]) -> bool:
        return (
            str(task.get("assigned_agent") or "") == "borg-implementation-drone"
            and str(task.get("description") or "").lstrip().startswith("<nano-implant>")
        )

    def _is_implementation_task_without_codeword(self, task: dict[str, Any]) -> bool:
        return (
            str(task.get("assigned_agent") or "") == "borg-implementation-drone"
            and not str(task.get("description") or "").lstrip().startswith("<nano-implant>")
        )

    def _maybe_pause_for_sparse_project(self, task: dict[str, Any]) -> dict[str, Any] | None:
        if self.local_llm_client is not None or self.claude_code_client is not None:
            return None
        snapshot = self._project_context_snapshot(task)
        if not snapshot.get("exists") or not snapshot.get("sparse"):
            return None
        if _looks_like_scaffold_request(task):
            self.task_repository.add_event(
                task["id"],
                "project_context_sparse",
                "Project directory contains no source/build markers; treating the task as an explicit scaffold request.",
                snapshot,
            )
            return None

        self.task_repository.add_event(
            task["id"],
            "project_context_missing",
            "Project directory contains no source/build markers. Add files, select a scaffold workflow, or clarify that a new project should be created.",
            snapshot,
        )
        self.task_repository.update_status(task["id"], "needs_input")
        return {"task_id": task["id"], "status": "needs_input", "reason": "sparse_project_context", "project": snapshot}

    def _run_implementation_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["id"]
        orchestration = self.orchestration_store.load()
        host_path, container_path = self._task_project_paths(task)
        workspace_project_root = self._task_project_root(task)
        mcp_config_json = self._pycharm_mcp_config_json(task)
        if self.claude_code_client is not None:
            client = self.claude_code_client
        else:
            client = ClaudeCodeClient(
                settings=self.settings,
                orchestration=orchestration,
                workspace=ClaudeCodeWorkspace(
                    project_root=workspace_project_root,
                    agents_source=self.settings.agents_root,
                    skills_source=self.settings.skills_root,
                )
                if workspace_project_root
                else None,
                mcp_config_json=mcp_config_json,
            )
        try:
            assets = client.ensure_project_assets()
        except Exception as exc:
            self.task_repository.add_event(
                task_id,
                "claude_assets_sync_failed",
                "Claude Code project agent and skill sync failed.",
                {"error": str(exc)},
            )
            raise RuntimeError(f"Claude Code asset sync failed: {exc}") from exc

        prompt = self._implementation_prompt(task)
        prompt = self._prepare_prompt_with_deep_guard(
            task_id,
            prompt,
            provider="claude_code",
            phase="implementation",
            iteration=1,
        )
        self.task_repository.add_event(
            task_id,
            "implementation_task_started",
            "Implementation Drone started the queued <nano-implant> task.",
            {
                "provider": "claude_code",
                "model": orchestration.local_model.model_name or orchestration.agent_selection.agent_name or "borg-cpu",
                "local_path": host_path or task.get("local_path"),
                "container_path": str(container_path) if container_path else None,
                "pycharm_mcp_enabled": bool(task.get("pycharm_mcp_enabled")),
            },
        )
        self.task_repository.add_event(
            task_id,
            "claude_assets_synced",
            "Claude Code project agents and skills are available in the project .claude directory.",
            assets,
        )
        self.task_repository.add_event(
            task_id,
            "llm_request",
            "Claude Code request sent for implementation.",
            {
                "iteration": 1,
                "phase": "implementation",
                "provider": "claude_code",
                "model": orchestration.local_model.model_name or orchestration.agent_selection.agent_name or "borg-cpu",
                "prompt": prompt,
            },
        )
        try:
            result = client.send_prompt(prompt)
        except ClaudeCodeClientError as exc:
            self.task_repository.add_event(
                task_id,
                "implementation_task_failed",
                "Claude Code implementation failed.",
                {"error": str(exc)},
            )
            raise RuntimeError(f"Claude Code implementation failed: {exc}") from exc

        output = str(result.get("content", "")).strip()
        _raise_if_tool_approval_loop(output)
        parsed = _parse_json_object(output)
        summary = str(parsed.get("summary") or output[:500]).strip()
        self.task_repository.add_event(
            task_id,
            "llm_response",
            "Claude Code implementation response received.",
            {
                "iteration": 1,
                "phase": "implementation",
                "provider": "claude_code",
                "response": output,
                "parsed": parsed,
                "command": result.get("command"),
                "stderr": result.get("stderr"),
            },
        )
        self.task_repository.add_event(
            task_id,
            "implementation_task_completed",
            "Implementation Drone completed the queued <nano-implant> task.",
            {
                "summary": summary,
                "modified_files": parsed.get("modified_files"),
                "tests": parsed.get("tests"),
                "verification": parsed.get("verification"),
            },
        )
        return {"task_id": task_id, "status": "done", "summary": summary}

    def _run_claude_code_processing(
        self,
        task: dict[str, Any],
        review_context: dict[str, str] | None,
        orchestration: OrchestrationSettings,
        *,
        phase: str = "planning",
        resume_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = task["id"]
        host_path, container_path = self._task_project_paths(task)
        workspace_project_root = self._task_project_root(task)
        mcp_config_json = self._pycharm_mcp_config_json(task)
        if self.claude_code_client is not None:
            client = self.claude_code_client
        else:
            client = ClaudeCodeClient(
                settings=self.settings,
                orchestration=orchestration,
                workspace=ClaudeCodeWorkspace(
                    project_root=workspace_project_root,
                    agents_source=self.settings.agents_root,
                    skills_source=self.settings.skills_root,
                )
                if workspace_project_root
                else None,
                mcp_config_json=mcp_config_json,
            )
        try:
            assets = client.ensure_project_assets()
        except Exception as exc:
            self.task_repository.add_event(
                task_id,
                "claude_assets_sync_failed",
                "Claude Code project agent and skill sync failed.",
                {"error": str(exc)},
            )
            raise RuntimeError(f"Claude Code asset sync failed: {exc}") from exc

        self.task_repository.add_event(
            task_id,
            "claude_assets_synced",
            "Claude Code project agents and skills are available in the project .claude directory.",
            assets,
        )
        prompt = self._claude_code_prompt(task, review_context, phase=phase, resume_context=resume_context)
        prompt = self._prepare_prompt_with_deep_guard(
            task_id,
            prompt,
            provider="claude_code",
            phase=phase,
            iteration=1,
        )
        event_type = "llm_resume_processing_started" if phase == "review_resume" else "llm_processing_started"
        self.task_repository.add_event(
            task_id,
            event_type,
            "Claude Code background delegation started.",
            {
                "provider": "claude_code",
                "phase": phase,
                "model": orchestration.local_model.model_name or orchestration.agent_selection.agent_name or "borg-cpu",
                "local_path": host_path or task.get("local_path"),
                "container_path": str(container_path) if container_path else None,
                "pycharm_mcp_enabled": bool(task.get("pycharm_mcp_enabled")),
                "review_context": review_context,
            },
        )
        if not bool(task.get("pycharm_mcp_enabled")):
            self.task_repository.add_event(
                task_id,
                "pycharm_mcp_skipped",
                "PyCharm MCP was not enabled for this task, so no IDE handoff was attempted.",
                {"enabled": False, "local_path": task.get("local_path")},
            )
        self.task_repository.add_event(
            task_id,
            "llm_request",
            "Claude Code request sent for agent delegation.",
            {
                "iteration": 1,
                "phase": phase,
                "provider": "claude_code",
                "model": orchestration.local_model.model_name or orchestration.agent_selection.agent_name or "borg-cpu",
                "prompt": prompt,
            },
        )
        try:
            result = client.send_prompt(prompt)
        except ClaudeCodeClientError as exc:
            failure_type = "llm_resume_processing_failed" if phase == "review_resume" else "llm_processing_failed"
            self.task_repository.add_event(
                task_id,
                failure_type,
                "Claude Code background delegation failed.",
                {"phase": phase, "error": str(exc)},
            )
            raise RuntimeError(f"Claude Code processing failed: {exc}") from exc

        output = str(result.get("content", "")).strip()
        _raise_if_tool_approval_loop(output)
        parsed = _parse_json_object(output)
        summary = str(parsed.get("summary") or output[:500]).strip()
        workspace_metadata = self._extract_workspace_metadata(parsed)
        extracted_specs = []
        stored_specs = []
        materialized_specs: list[str] = []
        materialized_project_files: list[str] = []
        if phase in {"planning", "review_resume"}:
            extracted_specs = self._extract_borg_cube_specs(task, parsed, output)
            stored_specs = self._store_borg_cube_specs(task, extracted_specs)
            materialized_specs = self._maybe_materialize_borg_cube_specs(task, assets, extracted_specs or stored_specs, parsed)
            materialized_project_files = self._maybe_materialize_project_files(task, assets, parsed)
            self._validate_new_borg_cube_project_completion(task, assets, extracted_specs, materialized_specs)
        created_tasks = self._store_implementation_tasks(task, parsed) if phase == "planning" else []
        stored_workspace_metadata = self._store_workspace_metadata(task, workspace_metadata)
        plan = {
            "summary": summary,
            "first_node_id": str(parsed["first_node_id"]) if parsed.get("first_node_id") else None,
            "iterations": [{"iteration": 1, "phase": phase, "output": output}],
            "provider": "claude_code",
            "claude_response": result.get("response"),
            "review_context": review_context,
            "stored_spec_count": len(stored_specs),
            "created_task_count": len(created_tasks),
            "materialized_project_file_count": len(materialized_project_files),
            "workspace_metadata": stored_workspace_metadata,
        }
        if resume_context:
            plan["resume_stage_index"] = int(resume_context.get("resume_stage_index", 1))

        self.task_repository.add_event(
            task_id,
            "llm_response",
            "Claude Code response received for agent delegation.",
            {
                "iteration": 1,
                "phase": phase,
                "provider": "claude_code",
                "model": orchestration.local_model.model_name or orchestration.agent_selection.agent_name or "borg-cpu",
                "response": output,
                "parsed": parsed,
                "command": result.get("command"),
                "stderr": result.get("stderr"),
                "workspace_metadata": stored_workspace_metadata,
            },
        )
        if stored_specs:
            self.task_repository.add_event(
                task_id,
                "borg_cube_specs_stored",
                "Claude Code borg-cube specifications were stored in the project database.",
                {
                    "project_id": task.get("project_id") or "local",
                    "count": len(stored_specs),
                    "paths": [spec.get("spec_path") for spec in stored_specs],
                    "materialized_paths": materialized_specs,
                },
            )
        if materialized_project_files:
            self.task_repository.add_event(
                task_id,
                "project_files_materialized",
                "Claude Code project scaffold files were written to the target project.",
                {
                    "count": len(materialized_project_files),
                    "paths": materialized_project_files,
                },
            )
        if created_tasks:
            self.task_repository.add_event(
                task_id,
                "implementation_tasks_created",
                "Disassembled implementation tasks were stored in the task database.",
                {
                    "count": len(created_tasks),
                    "task_ids": [created.get("id") for created in created_tasks],
                    "assigned_agent": "borg-implementation-drone",
                    "prompt_prefix": "<nano-implant>",
                },
            )
        if stored_workspace_metadata:
            self.task_repository.add_event(
                task_id,
                "workspace_metadata_updated",
                "Workspace metadata was stored for the active task.",
                stored_workspace_metadata,
            )
        self.task_repository.add_event(
            task_id,
            "llm_iteration_completed",
            "Claude Code delegation iteration completed.",
            {
                "iteration": 1,
                "phase": phase,
                "provider": "claude_code",
                "prompt": prompt,
                "output": output,
                "parsed": parsed,
                "workspace_metadata": stored_workspace_metadata,
            },
        )
        completed_type = "llm_resume_processing_completed" if phase == "review_resume" else "llm_processing_completed"
        self.task_repository.add_event(
            task_id,
            completed_type,
            "Claude Code completed background delegation; workflow node selection can begin.",
            {
                "summary": summary,
                "first_node_id": plan["first_node_id"],
                "resume_stage_index": plan.get("resume_stage_index"),
                "human_review_text": self._render_llm_human_review_text(plan),
                "provider": "claude_code",
                "workspace_metadata": stored_workspace_metadata,
            },
        )
        return plan

    def _prepare_prompt_with_deep_guard(
        self,
        task_id: str,
        prompt: str,
        *,
        provider: str,
        phase: str,
        iteration: int,
    ) -> str:
        if "<deep>" in prompt:
            return prompt
        similar_streak = self._recent_similar_llm_response_streak(task_id)
        if similar_streak < 3:
            return prompt
        escalated = f"<deep>\n{prompt}"
        self.task_repository.add_event(
            task_id,
            "llm_deep_escalation_requested",
            "Detected repeated similar LLM results; escalating next prompt to deep model mode.",
            {
                "provider": provider,
                "phase": phase,
                "iteration": iteration,
                "similar_response_streak": similar_streak,
                "guard": "similar_response_limit",
                "limit": 3,
            },
        )
        return escalated

    def _recent_similar_llm_response_streak(self, task_id: str) -> int:
        events = self.task_repository.list_events(task_id)
        responses: list[str] = []
        for event in events:
            if event.get("event_type") != "llm_response":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            response = _clean_text(payload.get("response"))
            if response:
                responses.append(response)
        if not responses:
            return 0

        # Count a trailing streak of equal/similar responses to detect non-productive loops.
        anchor = responses[-1]
        streak = 1
        for candidate in reversed(responses[:-1]):
            if _responses_similar(anchor, candidate):
                streak += 1
                continue
            break
        return streak

    def _claude_code_prompt(
        self,
        task: dict[str, Any],
        review_context: dict[str, str] | None,
        *,
        phase: str,
        resume_context: dict[str, Any] | None,
    ) -> str:
        host_path, container_path = self._task_project_paths(task)
        assigned_agent = task.get("assigned_agent") or "borg-queen-architect"
        if str(assigned_agent) in {"local-llm", "mock-agent"}:
            assigned_agent = "borg-queen-architect"
        lines = [
            "Run this Borg Universe task through Claude Code in background mode.",
            "Use project subagents from `.claude/agents` and project skills from `.claude/skills`.",
            "Prefer project-local agents and skills over global equivalents.",
            f"Delegate first to the `{assigned_agent}` subagent unless the workflow context specifies a more precise node agent.",
            "Return compact JSON with keys: summary, first_node_id, borg_cube_specs, implementation_tasks, delegated_agents, verification.",
            "borg_cube_specs must contain project and module specs as objects with spec_path, spec_type, title, summary, content.",
            "The project spec path is borg-cube.md and must list the module specs underneath it.",
            "Each module spec path ends with borg-cube.md and briefly explains that module's available capabilities.",
            "Store specs in the project database by default. Set materialize_borg_cube_files true only when the user explicitly requests files or when workflow_id is new_borg_cube_project.",
            "For workflow_id new_borg_cube_project, also return project_files for a minimal runnable scaffold when the target project is empty or missing core project files.",
            "project_files must be a list of objects with path and content. Use relative paths only and include only safe text files required for the base scaffold.",
            "implementation_tasks must be small, focused work items. Every implementation prompt must start with <nano-implant>.",
            f"Phase: {phase}",
            f"Title: {task.get('title')}",
            f"Description: {task.get('description')}",
            f"Target project path on host: {host_path or task.get('local_path')}",
            f"Target project path in container: {container_path or host_path or task.get('local_path')}",
            f"PyCharm MCP enabled: {bool(task.get('pycharm_mcp_enabled'))}",
            f"Workflow: {task.get('workflow_id')}",
        ]
        lines.extend(self._workspace_metadata_prompt_lines(task))
        lines.extend(_sandbox_safe_workspace_lines(container_path or host_path or task.get("local_path")))
        if bool(task.get("pycharm_mcp_enabled")):
            lines.append("Use the PyCharm MCP file tools for project file reads and writes when they are available.")
        lines.extend(self._project_context_prompt_lines(task))
        if resume_context:
            lines.append(f"Resume workflow stage index: {resume_context.get('resume_stage_index', 1)}")
            lines.append("The workflow stage is already selected by Borg Universe; do not override it.")
        if review_context:
            lines.append("Human review context:")
            if review_context.get("notes"):
                lines.append(f"Review notes: {review_context['notes']}")
            if review_context.get("summary"):
                lines.append(f"Previous summary: {review_context['summary']}")
            if review_context.get("output"):
                lines.append("Previous output:")
                lines.append(review_context["output"])
        lines.extend(self._claude_workflow_context_lines(task))
        return "\n".join(lines)

    def _pycharm_mcp_config_json(self, task: dict[str, Any]) -> str | None:
        if not bool(task.get("pycharm_mcp_enabled")):
            return None

        endpoint = self._pycharm_mcp_endpoint(task)
        if not endpoint:
            return None

        transport, url = endpoint
        config = {
            "mcpServers": {
                "pycharm": {
                    "type": transport,
                    "url": url,
                }
            }
        }
        return json.dumps(config, ensure_ascii=False)

    def _pycharm_mcp_endpoint(self, task: dict[str, Any]) -> tuple[str, str] | None:
        for candidate in (task, self._project_for_task(task)):
            if not candidate:
                continue
            stream_url = _clean_text(candidate.get("pycharm_mcp_stream_url"))
            if stream_url:
                return ("http", stream_url)
            sse_url = _clean_text(candidate.get("pycharm_mcp_sse_url"))
            if sse_url:
                return ("sse", sse_url)
        return None

    def _project_for_task(self, task: dict[str, Any]) -> dict[str, Any] | None:
        project_id = _clean_text(task.get("project_id"))
        if not project_id:
            return None
        client = getattr(self.task_repository, "client", None)
        if client is None or not hasattr(client, "request"):
            return None
        try:
            rows = client.request(
                "GET",
                "projects",
                query={"select": "*", "id": f"eq.{project_id}", "limit": "1"},
            )
        except Exception:
            return None
        return rows[0] if rows else None

    def _task_project_paths(self, task: dict[str, Any]) -> tuple[str | None, Path | None]:
        workspace_metadata = self._task_workspace_metadata(task)
        active_workspace = _clean_text(workspace_metadata.get("worktree_path")) if workspace_metadata else None
        if active_workspace:
            container_path = _map_workbench_path(active_workspace)
            return active_workspace, container_path
        host_path = _clean_text(task.get("local_path"))
        if not host_path:
            return None, None
        container_path = _map_workbench_path(host_path)
        return host_path, container_path

    def _task_project_root(self, task: dict[str, Any]) -> Path | None:
        host_path, container_path = self._task_project_paths(task)
        if container_path and container_path.exists():
            return container_path
        if host_path:
            try:
                host_root = Path(host_path).expanduser()
                if host_root.exists():
                    return host_root
            except Exception:
                pass
        if container_path:
            return container_path
        if host_path:
            try:
                return Path(host_path).expanduser()
            except Exception:
                return None
        return None

    def _project_context_prompt_lines(self, task: dict[str, Any]) -> list[str]:
        snapshot = self._project_context_snapshot(task)
        if not snapshot.get("exists"):
            return []
        lines = ["Project context snapshot:"]
        if snapshot.get("sparse"):
            lines.append("- No source/build markers were found. Treat this as an empty scaffold only if the task explicitly requests project creation.")
        markers = snapshot.get("markers")
        if isinstance(markers, list) and markers:
            lines.append(f"- Detected markers: {', '.join(str(marker) for marker in markers)}")
        ignored = snapshot.get("ignored_top_level")
        if isinstance(ignored, list) and ignored:
            lines.append(f"- Ignored metadata directories: {', '.join(str(item) for item in ignored)}")
        return lines

    def _task_workspace_metadata(self, task: dict[str, Any]) -> dict[str, Any]:
        raw = task.get("workspace_metadata")
        return raw if isinstance(raw, dict) else {}

    def _workspace_metadata_prompt_lines(self, task: dict[str, Any]) -> list[str]:
        workspace = self._task_workspace_metadata(task)
        if not workspace:
            return []
        lines = ["Workspace metadata:"]
        for key in (
            "workspace_id",
            "workflow_id",
            "task_id",
            "node_id",
            "branch_name",
            "worktree_path",
            "base_commit",
            "head_commit",
            "lifecycle_state",
        ):
            value = workspace.get(key)
            if value is None or value == "":
                continue
            lines.append(f"- {key}: {value}")
        return lines

    def _extract_workspace_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = next(
            (
                candidate
                for candidate in (
                    payload.get("workspace_metadata"),
                    payload.get("workspace"),
                    payload.get("active_workspace"),
                )
                if isinstance(candidate, dict)
            ),
            None,
        )
        if not isinstance(source, dict):
            return {}
        normalized: dict[str, Any] = {}
        for key in (
            "workspace_id",
            "workflow_id",
            "task_id",
            "node_id",
            "branch_name",
            "worktree_path",
            "base_commit",
            "head_commit",
            "lifecycle_state",
        ):
            value = _clean_text(source.get(key))
            if value:
                normalized[key] = value
        retry_index = source.get("retry_index")
        if isinstance(retry_index, int):
            normalized["retry_index"] = retry_index
        elif isinstance(retry_index, str) and retry_index.strip().isdigit():
            normalized["retry_index"] = int(retry_index.strip())
        return normalized

    def _store_workspace_metadata(self, task: dict[str, Any], workspace_metadata: dict[str, Any]) -> dict[str, Any]:
        if not workspace_metadata:
            return self._task_workspace_metadata(task)
        merged = {**self._task_workspace_metadata(task), **workspace_metadata}
        updated = self.task_repository.update_fields(task["id"], {"workspace_metadata": merged})
        task["workspace_metadata"] = (
            updated.get("workspace_metadata") if isinstance(updated, dict) else merged
        ) or merged
        return dict(task.get("workspace_metadata") or merged)

    def _project_context_snapshot(self, task: dict[str, Any]) -> dict[str, Any]:
        root = self._task_project_root(task)
        if root is None:
            return {"exists": False, "path": None}
        if not root.exists() or not root.is_dir():
            return {"exists": False, "path": str(root)}

        ignored_names = {".claude", ".git", ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "venv"}
        marker_names = {
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "pytest.ini",
            "tox.ini",
            "CMakeLists.txt",
            "CMakePresets.json",
            "Makefile",
            "west.yml",
            "prj.conf",
            "platformio.ini",
        }
        marker_suffixes = (".ioc", ".uvprojx", ".eww", ".ld", ".overlay", ".conf")

        ignored_top_level: list[str] = []
        content_top_level: list[str] = []
        markers: list[str] = []
        for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if child.name in ignored_names:
                ignored_top_level.append(child.name)
                continue
            content_top_level.append(child.name)
            if child.name in marker_names or child.suffix.lower() in marker_suffixes:
                markers.append(child.name)

        if not markers:
            for path in root.rglob("*"):
                relative_parts = path.relative_to(root).parts
                if any(part in ignored_names for part in relative_parts):
                    continue
                if path.is_file() and (path.name in marker_names or path.suffix.lower() in marker_suffixes):
                    markers.append(str(path.relative_to(root)).replace("\\", "/"))
                    if len(markers) >= 20:
                        break

        return {
            "exists": True,
            "path": str(root),
            "sparse": not content_top_level and not markers,
            "markers": markers[:20],
            "ignored_top_level": ignored_top_level,
            "content_top_level": content_top_level[:20],
        }

    def _claude_workflow_context_lines(self, task: dict[str, Any]) -> list[str]:
        workflow_id = task.get("workflow_id")
        if not workflow_id:
            return []
        try:
            workflow = self.workflow_store.get_workflow(str(workflow_id))
        except WorkflowStoreError:
            return []
        if not workflow:
            return []
        lines = ["Workflow agent context:"]
        for stage_index, stage in enumerate(self.workflow_store.build_stages(workflow), start=1):
            lines.append(f"Level {stage_index}: {stage.title} ({stage.mode})")
            for node in stage.nodes:
                skills = self._select_skills(node, task)
                lines.append(
                    f"- node_id={node.id}; agent={node.agent or 'default'}; borg_name={node.borg_name}; skills={', '.join(skills) or 'none'}"
                )
                for workflow_task in node.tasks:
                    if workflow_task.prompt:
                        lines.append(f"  task={workflow_task.id}: {workflow_task.prompt}")
        return lines

    def _store_borg_cube_specs(
        self,
        task: dict[str, Any],
        specs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not specs:
            return []
        client = getattr(self.task_repository, "client", None)
        if client is None or not hasattr(client, "request"):
            return []
        try:
            return ProjectSpecRepository(client).upsert_specs(specs)
        except SupabaseRestError as exc:
            self.task_repository.add_event(
                task["id"],
                "borg_cube_specs_storage_failed",
                "Claude Code borg-cube specifications could not be stored, but the workflow will continue.",
                {
                    "error": str(exc),
                    "status_code": exc.status_code,
                    "project_id": task.get("project_id") or "local",
                    "count": len(specs),
                },
            )
            return []

    def _validate_new_borg_cube_project_completion(
        self,
        task: dict[str, Any],
        assets: dict[str, Any],
        specs: list[dict[str, Any]],
        materialized_paths: list[str],
    ) -> None:
        if str(task.get("workflow_id") or "") != "new_borg_cube_project":
            return
        project_root = Path(str(assets.get("project_root") or self.settings.borg_root))
        root_spec = project_root / "borg-cube.md"
        errors: list[str] = []
        if not specs:
            errors.append("no borg_cube_specs were returned")
        if not root_spec.exists():
            errors.append("borg-cube.md was not materialized at the project root")
        else:
            errors.extend(_borg_cube_quality_errors(root_spec.read_text(encoding="utf-8")))
        if errors:
            payload = {
                "project_root": str(project_root),
                "spec_path": str(root_spec),
                "materialized_paths": materialized_paths,
                "errors": errors,
            }
            self.task_repository.add_event(
                task["id"],
                "borg_cube_spec_validation_failed",
                "New Borg Cube Project did not produce a clean root borg-cube.md specification.",
                payload,
            )
            raise RuntimeError("New Borg Cube Project did not produce a clean borg-cube.md: " + "; ".join(errors))
        self.task_repository.add_event(
            task["id"],
            "borg_cube_spec_validated",
            "New Borg Cube Project produced a clean root borg-cube.md specification.",
            {
                "project_root": str(project_root),
                "spec_path": str(root_spec),
                "materialized_paths": materialized_paths,
            },
        )

    def _extract_borg_cube_specs(
        self,
        task: dict[str, Any],
        parsed: dict[str, Any],
        output: str,
    ) -> list[dict[str, Any]]:
        project_id = str(task.get("project_id") or "local")
        raw_specs = parsed.get("borg_cube_specs")
        specs: list[dict[str, Any]] = []
        if isinstance(raw_specs, list):
            for raw_spec in raw_specs:
                if not isinstance(raw_spec, dict):
                    continue
                content = _clean_text(raw_spec.get("content"))
                spec_path = _normalize_spec_path(raw_spec.get("spec_path") or raw_spec.get("path"))
                if not content or not spec_path:
                    continue
                specs.append(
                    {
                        "project_id": project_id,
                        "spec_path": spec_path,
                        "spec_type": _spec_type(raw_spec.get("spec_type"), spec_path),
                        "module_name": _clean_text(raw_spec.get("module_name")),
                        "title": _clean_text(raw_spec.get("title")) or _title_from_spec_path(spec_path),
                        "summary": _clean_text(raw_spec.get("summary")) or "",
                        "content": content.rstrip() + "\n",
                        "source": "claude_code",
                    }
                )

        if specs:
            return specs

        cube_content = ""
        if isinstance(parsed.get("borg_cube_md"), str) and parsed["borg_cube_md"].strip():
            cube_content = parsed["borg_cube_md"].strip()
        elif output.lstrip().startswith(("#", "---")):
            cube_content = output.strip()
        if not cube_content:
            return []
        return [
            {
                "project_id": project_id,
                "spec_path": "borg-cube.md",
                "spec_type": "project",
                "module_name": None,
                "title": "Project borg-cube",
                "summary": str(parsed.get("summary") or "")[:500],
                "content": cube_content.rstrip() + "\n",
                "source": "claude_code",
            }
        ]

    def _maybe_materialize_borg_cube_specs(
        self,
        task: dict[str, Any],
        assets: dict[str, Any],
        specs: list[dict[str, Any]],
        parsed: dict[str, Any],
    ) -> list[str]:
        requested = (
            bool(parsed.get("materialize_borg_cube_files"))
            or _env_bool("BORG_CUBE_WRITE_FILES", False)
            or str(task.get("workflow_id") or "") == "new_borg_cube_project"
        )
        if not requested or not specs:
            return []
        project_root = Path(str(assets.get("project_root") or self.settings.borg_root))
        written: list[str] = []
        for spec in specs:
            spec_path = _normalize_spec_path(spec.get("spec_path"))
            content = _clean_text(spec.get("content"))
            if not spec_path or not content:
                continue
            target = project_root / spec_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.rstrip() + "\n", encoding="utf-8")
            written.append(str(target))
        return written

    def _maybe_materialize_project_files(
        self,
        task: dict[str, Any],
        assets: dict[str, Any],
        parsed: dict[str, Any],
    ) -> list[str]:
        if str(task.get("workflow_id") or "") != "new_borg_cube_project":
            return []
        raw_files = parsed.get("project_files")
        if not isinstance(raw_files, list):
            return []

        project_root = Path(str(assets.get("project_root") or self.settings.borg_root))
        written: list[str] = []
        for raw_file in raw_files:
            if not isinstance(raw_file, dict):
                continue
            relative_path = _normalize_project_file_path(raw_file.get("path") or raw_file.get("file_path"))
            content = _clean_text(raw_file.get("content"))
            if not relative_path or content is None:
                continue
            target = project_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.rstrip() + "\n", encoding="utf-8")
            written.append(str(target))
        return written

    def _store_implementation_tasks(self, parent_task: dict[str, Any], parsed: dict[str, Any]) -> list[dict[str, Any]]:
        raw_tasks = parsed.get("implementation_tasks") or parsed.get("tasks")
        if not isinstance(raw_tasks, list):
            return []
        created: list[dict[str, Any]] = []
        for index, raw_task in enumerate(raw_tasks, start=1):
            if not isinstance(raw_task, dict):
                continue
            title = _clean_text(raw_task.get("title")) or f"Implementation task {index}"
            prompt = _clean_text(raw_task.get("prompt") or raw_task.get("description") or raw_task.get("goal")) or title
            if not prompt.startswith("<nano-implant>"):
                prompt = f"<nano-implant> {prompt}"
            workspace_metadata = self._extract_workspace_metadata(raw_task)
            description_parts = [
                prompt,
                "",
                f"Parent task: {parent_task.get('id')}",
            ]
            depends_on = raw_task.get("depends_on")
            if isinstance(depends_on, list) and depends_on:
                description_parts.append(f"Depends on: {', '.join(str(item) for item in depends_on)}")
            try:
                created.append(
                    self.task_repository.create_task(
                        TaskCreate(
                            title=title[:200],
                            description="\n".join(description_parts).strip(),
                            project_id=parent_task.get("project_id"),
                            workflow_id=None,
                            target_platform=parent_task.get("target_platform"),
                            target_mcu=parent_task.get("target_mcu"),
                            board=parent_task.get("board"),
                            local_path=parent_task.get("local_path"),
                            pycharm_mcp_enabled=bool(parent_task.get("pycharm_mcp_enabled")),
                            topic=parent_task.get("topic"),
                            requested_by=parent_task.get("requested_by"),
                            assigned_agent="borg-implementation-drone",
                            assigned_skill="implementation",
                            sequence_index=index,
                            workspace_metadata=workspace_metadata,
                        ),
                        initial_status="draft",
                    )
                )
            except Exception as exc:
                self.task_repository.add_event(
                    parent_task["id"],
                    "implementation_task_create_failed",
                    f"Implementation task could not be stored: {title}",
                    {"error": str(exc), "title": title},
                )
        return created

    def _implementation_prompt(self, task: dict[str, Any]) -> str:
        description = str(task.get("description") or "").strip()
        host_path, container_path = self._task_project_paths(task)
        lines = [
            description,
            "",
            "Run the `borg-implementation-drone` subagent for this exact task.",
            "Implement exactly one stored implementation task. Do not merge scope from sibling tasks.",
            "Use project-local `.claude/agents` and `.claude/skills` when available.",
            "Modify project files as needed, run focused verification, and return compact JSON.",
            "Return keys: summary, modified_files, tests, verification, blockers.",
            f"Task ID: {task.get('id')}",
            f"Title: {task.get('title')}",
            f"Target project path on host: {host_path or task.get('local_path')}",
            f"Target project path in container: {container_path or host_path or task.get('local_path')}",
            f"PyCharm MCP enabled: {bool(task.get('pycharm_mcp_enabled'))}",
        ]
        lines.extend(self._workspace_metadata_prompt_lines(task))
        lines.extend(_sandbox_safe_workspace_lines(container_path or host_path or task.get("local_path")))
        spec_context = self._implementation_spec_context(task)
        if spec_context:
            lines.extend(["", "Stored borg-cube specs:", spec_context])
        return "\n".join(lines).strip()

    def _implementation_spec_context(self, task: dict[str, Any]) -> str:
        project_id = _clean_text(task.get("project_id"))
        client = getattr(self.task_repository, "client", None)
        if not project_id or client is None or not hasattr(client, "request"):
            return ""
        try:
            specs = ProjectSpecRepository(client).list_for_project(project_id)
        except Exception:
            return ""

        lines: list[str] = []
        remaining = 12000
        for spec in specs:
            path = str(spec.get("spec_path") or "")
            title = str(spec.get("title") or "")
            summary = str(spec.get("summary") or "")
            content = str(spec.get("content") or "")
            block = f"## {path} - {title}\n{summary}\n\n{content}".strip()
            if len(block) > remaining:
                block = block[:remaining].rstrip()
            if block:
                lines.append(block)
                remaining -= len(block)
            if remaining <= 0:
                break
        return "\n\n".join(lines)

    def _llm_planning_prompt(self, task: dict[str, Any], review_context: dict[str, str] | None = None) -> str:
        review_lines: list[str] = []
        if review_context:
            review_lines.append("Human review context:")
            if review_context.get("notes"):
                review_lines.append(f"Review notes: {review_context['notes']}")
            if review_context.get("summary"):
                review_lines.append(f"LLM summary: {review_context['summary']}")
            if review_context.get("output"):
                review_lines.append("LLM output:")
                review_lines.append(review_context["output"])
        return (
            "You are the local agentic execution system. Plan the task, identify needed steps, "
            "and prepare for iterative execution. Use the local path and PyCharm MCP state when relevant.\n"
            + (("\n".join(review_lines) + "\n") if review_lines else "")
            + f"Title: {task.get('title')}\n"
            + f"Description: {task.get('description')}\n"
            + f"Local path: {task.get('local_path')}\n"
            + f"PyCharm MCP enabled: {bool(task.get('pycharm_mcp_enabled'))}\n"
            + f"Workflow: {task.get('workflow_id')}"
        )

    def _llm_review_resume_prompt(
        self,
        task: dict[str, Any],
        review_context: dict[str, str] | None,
        stage_index: int,
    ) -> str:
        host_path, container_path = self._task_project_paths(task)
        lines = [
            "You are resuming an agentic workflow after human review.",
            "The workflow stage is already selected by the system; do not choose or change the first node.",
            "Use the human review notes as authoritative input for the next workflow level.",
            "Return a concise implementation handoff with risks, required file actions, and verification steps.",
            f"Next workflow level: {stage_index + 1}",
            f"Title: {task.get('title')}",
            f"Description: {task.get('description')}",
            f"Local path on host: {host_path or task.get('local_path')}",
            f"Local path in container: {container_path or host_path or task.get('local_path')}",
            f"PyCharm MCP enabled: {bool(task.get('pycharm_mcp_enabled'))}",
            f"Workflow: {task.get('workflow_id')}",
        ]
        if review_context:
            lines.append("Human review context:")
            if review_context.get("notes"):
                lines.append(f"Review notes: {review_context['notes']}")
            if review_context.get("summary"):
                lines.append(f"Previous LLM summary: {review_context['summary']}")
            if review_context.get("output"):
                lines.append("Previous LLM output:")
                lines.append(review_context["output"])
        else:
            lines.append("Human review context: none recorded.")
        return "\n".join(lines)

    def _latest_review_context(self, events: list[dict[str, Any]]) -> dict[str, str] | None:
        latest: dict[str, str] = {}
        for event in events:
            event_type = str(event.get("event_type") or "")
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if event_type == "review_noted" and payload.get("notes"):
                latest["notes"] = str(payload.get("notes") or "")
            elif event_type in ("review_confirmed", "human_review_confirmed") and payload.get("notes"):
                latest["notes"] = str(payload.get("notes") or latest.get("notes") or "")
            elif event_type == "llm_processing_completed":
                if payload.get("summary"):
                    latest["summary"] = str(payload.get("summary") or "")
                if payload.get("human_review_text"):
                    latest["output"] = str(payload.get("human_review_text") or "")
        return latest or None

    def _run_workflow(
        self,
        task: dict[str, Any],
        default_agent_name: str,
        llm_plan: dict[str, Any],
        stage_index: int = 0,
    ) -> dict[str, Any]:
        workflow_id = task.get("workflow_id")
        if not workflow_id:
            return {"paused_for_review": False, "completed_all_stages": False, "uses_explicit_review": False, "executed_stage_count": 0}

        try:
            workflow = self.workflow_store.get_workflow(str(workflow_id))
        except WorkflowStoreError as exc:
            self.task_repository.add_event(
                task["id"],
                "workflow_unavailable",
                "Selected workflow could not be loaded.",
                {"workflow_id": workflow_id, "error": str(exc)},
            )
            return {"paused_for_review": False, "completed_all_stages": False, "uses_explicit_review": False, "executed_stage_count": 0}
        if not workflow:
            self.task_repository.add_event(
                task["id"],
                "workflow_unavailable",
                "Selected workflow was not found.",
                {"workflow_id": workflow_id},
            )
            return {"paused_for_review": False, "completed_all_stages": False, "uses_explicit_review": False, "executed_stage_count": 0}

        stages = self.workflow_store.build_stages(workflow)
        if not stages:
            return {"paused_for_review": False, "completed_all_stages": False, "uses_explicit_review": False, "executed_stage_count": 0}

        bounded_stage_index = min(max(stage_index, 0), len(stages) - 1)
        uses_explicit_review = self._workflow_uses_explicit_review_stages(workflow, stages)
        current_stage_index = bounded_stage_index
        executed_stage_count = 0
        while current_stage_index < len(stages):
            stage = stages[current_stage_index]
            stage_id = workflow.steps[current_stage_index].id if current_stage_index < len(workflow.steps) else stage.title
            if uses_explicit_review and self._stage_requires_human_review(workflow, current_stage_index, stage):
                next_stage_index = current_stage_index + 1 if current_stage_index + 1 < len(stages) else None
                self.task_repository.add_event(
                    task["id"],
                    "workflow_review_required",
                    "Workflow reached a human review checkpoint and paused before executing it.",
                    {
                        "workflow_id": workflow.id,
                        "review_stage_id": stage_id,
                        "review_stage_index": current_stage_index,
                        "review_stage_title": stage.title,
                        "next_stage_index": next_stage_index,
                    },
                )
                return {
                    "paused_for_review": True,
                    "completed_all_stages": False,
                    "uses_explicit_review": True,
                    "executed_stage_count": executed_stage_count,
                    "review_stage_index": current_stage_index,
                    "review_stage_id": stage_id,
                    "next_stage_index": next_stage_index,
                }

            if bounded_stage_index > 0:
                print(f"[WORKFLOW] advancing to post-review stage: {stage.title}")
                print("[WORKER] executing post-review stage")
                if "plan" in stage.title.lower():
                    print("[PLANNER] recomputed cube plan")
                if "synthesis" in stage.title.lower():
                    print("[SYNTHESIS] generating cube files")
            self._run_workflow_stage(task, workflow, default_agent_name, llm_plan, current_stage_index, stage)
            executed_stage_count += 1
            current_stage_index += 1
            if not uses_explicit_review:
                break

        return {
            "paused_for_review": False,
            "completed_all_stages": current_stage_index >= len(stages),
            "uses_explicit_review": uses_explicit_review,
            "executed_stage_count": executed_stage_count,
            "next_stage_index": current_stage_index if current_stage_index < len(stages) else None,
        }

    def _run_workflow_stage(
        self,
        task: dict[str, Any],
        workflow: WorkflowDefinition,
        default_agent_name: str,
        llm_plan: dict[str, Any],
        stage_index: int,
        stage: Any,
    ) -> None:
        stage_id = workflow.steps[stage_index].id if stage_index < len(workflow.steps) else stage.title
        nodes = self._ordered_stage_nodes(workflow, stage.nodes, llm_plan.get("first_node_id"))
        self.task_repository.add_event(
            task["id"],
            "workflow_stage_started",
            f"Workflow level {stage_index + 1} started: {stage.title}.",
            {
                "workflow_id": workflow.id,
                "stage_id": stage_id,
                "stage_index": stage_index,
                "stage_title": stage.title,
                "stage_mode": stage.mode,
            },
        )
        if nodes:
            self.task_repository.add_event(
                task["id"],
                "workflow_first_node_selected",
                "First workflow node selected after local LLM processing.",
                {
                    "workflow_id": workflow.id,
                    "node_id": nodes[0].id,
                    "llm_plan": llm_plan,
                    "stage_id": stage_id,
                    "stage_index": stage_index,
                },
            )

        command_results: list[dict[str, Any]] = []
        for index, node in enumerate(nodes, start=1):
            agent_name = node.agent or default_agent_name
            selected_skills = self._select_skills(node, task)
            workspace_action = self._workspace_audit_action(node)
            if workspace_action:
                self.task_repository.add_event(
                    task["id"],
                    f"workspace_{workspace_action}_started",
                    f"Workspace {workspace_action} phase started.",
                    self._workspace_audit_payload(
                        task=task,
                        workflow=workflow,
                        stage_id=stage_id,
                        stage_index=stage_index,
                        node=node,
                        agent_name=agent_name,
                        sequence=index,
                    ),
                )
            self.task_repository.add_event(
                task["id"],
                "workflow_agent_invoked",
                f"Workflow invoked {agent_name} for node {node.borg_name}.",
                {
                    "workflow_id": workflow.id,
                    "node_id": node.id,
                    "agent_name": agent_name,
                    "sequence": index,
                    "stage_id": stage_id,
                    "stage_index": stage_index,
                },
            )
            self.task_repository.add_event(
                task["id"],
                "workflow_skills_selected",
                f"{agent_name} selected skills for node {node.borg_name}.",
                {
                    "workflow_id": workflow.id,
                    "node_id": node.id,
                    "agent_name": agent_name,
                    "skills": selected_skills,
                    "stage_id": stage_id,
                    "stage_index": stage_index,
                },
            )
            command_results.extend(
                self._run_node_command_gates(
                    parent_task=task,
                    workflow=workflow,
                    stage_id=stage_id,
                    stage_index=stage_index,
                    node=node,
                )
            )
            if workspace_action:
                self.task_repository.add_event(
                    task["id"],
                    f"workspace_{workspace_action}_completed",
                    f"Workspace {workspace_action} phase completed.",
                    self._workspace_audit_payload(
                        task=task,
                        workflow=workflow,
                        stage_id=stage_id,
                        stage_index=stage_index,
                        node=node,
                        agent_name=agent_name,
                        sequence=index,
                        command_results=command_results,
                    ),
                )
        triggered_tasks = []
        if self._is_implementation_trigger_stage(stage_id, nodes):
            triggered_tasks = self._trigger_implementation_tasks(
                task,
                workflow_id=workflow.id,
                stage_id=stage_id,
                stage_index=stage_index,
            )
        self.task_repository.add_event(
            task["id"],
            "workflow_stage_completed",
            f"Workflow level {stage_index + 1} completed: {stage.title}.",
            {
                "workflow_id": workflow.id,
                "stage_id": stage_id,
                "stage_index": stage_index,
                "stage_title": stage.title,
                "next_stage_index": stage_index + 1 if stage_index + 1 < len(self.workflow_store.build_stages(workflow)) else None,
                "triggered_implementation_task_ids": [queued.get("id") for queued in triggered_tasks],
                "command_results": command_results,
            },
        )

    def _workflow_uses_explicit_review_stages(self, workflow: WorkflowDefinition, stages: list[Any]) -> bool:
        return any(self._stage_requires_human_review(workflow, index, stage) for index, stage in enumerate(stages))

    def _workspace_audit_action(self, node: WorkflowNode) -> str | None:
        candidates = [node.id, node.borg_name, node.role]
        for workflow_task in node.tasks:
            candidates.extend([workflow_task.id, workflow_task.title, workflow_task.prompt])
        normalized = " ".join(str(candidate or "").lower() for candidate in candidates)
        if "workspace_orchestrator" not in normalized and "git-" not in normalized and "worktree" not in normalized:
            return None
        if "prepare" in normalized:
            return "prepare"
        if "finalize" in normalized:
            return "finalize"
        if " lock" in f" {normalized}" or "locked" in normalized:
            return "lock"
        if any(token in normalized for token in ("cleanup", "clean up", "remove", "prune", "discard", "archive")):
            return "cleanup"
        return None

    def _workspace_audit_payload(
        self,
        *,
        task: dict[str, Any],
        workflow: WorkflowDefinition,
        stage_id: str,
        stage_index: int,
        node: WorkflowNode,
        agent_name: str,
        sequence: int,
        command_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "workflow_id": workflow.id,
            "stage_id": stage_id,
            "stage_index": stage_index,
            "node_id": node.id,
            "node_role": node.role,
            "agent_name": agent_name,
            "sequence": sequence,
            "workspace_metadata": self._task_workspace_metadata(task),
        }
        if command_results is not None:
            payload["command_results"] = command_results
        return payload

    def _stage_requires_human_review(self, workflow: WorkflowDefinition, stage_index: int, stage: Any) -> bool:
        stage_id = workflow.steps[stage_index].id if stage_index < len(workflow.steps) else stage.title
        candidates = [stage_id, stage.title]
        for node in stage.nodes:
            candidates.extend([node.id, node.borg_name, node.role])
            for workflow_task in node.tasks:
                candidates.extend([workflow_task.id, workflow_task.title, workflow_task.prompt])
        normalized = " ".join(str(candidate or "").lower() for candidate in candidates)
        return "human-review" in normalized or "human review" in normalized

    def _run_node_command_gates(
        self,
        *,
        parent_task: dict[str, Any],
        workflow: WorkflowDefinition,
        stage_id: str,
        stage_index: int,
        node: WorkflowNode,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for workflow_task in node.tasks:
            for command_index, command in enumerate(self._workflow_task_commands(workflow_task), start=1):
                results.append(
                    self._run_workflow_command(
                        parent_task=parent_task,
                        workflow=workflow,
                        stage_id=stage_id,
                        stage_index=stage_index,
                        node=node,
                        workflow_task=workflow_task,
                        command=command,
                        command_index=command_index,
                    )
                )
        return results

    def _workflow_task_commands(self, workflow_task: WorkflowTask) -> list[WorkflowCommand]:
        commands: list[WorkflowCommand] = []
        if workflow_task.command:
            commands.append(self._coerce_workflow_command(workflow_task.command))
        for command in workflow_task.commands:
            commands.append(self._coerce_workflow_command(command))
        return commands

    def _coerce_workflow_command(self, command: str | WorkflowCommand) -> WorkflowCommand:
        if isinstance(command, WorkflowCommand):
            return command
        return WorkflowCommand(run=str(command))

    def _run_workflow_command(
        self,
        *,
        parent_task: dict[str, Any],
        workflow: WorkflowDefinition,
        stage_id: str,
        stage_index: int,
        node: WorkflowNode,
        workflow_task: WorkflowTask,
        command: WorkflowCommand,
        command_index: int,
    ) -> dict[str, Any]:
        command_id = command.id or f"{workflow_task.id}-{command_index}"
        cwd = _resolve_command_path(
            self._task_project_root(parent_task) or self.settings.borg_root,
            command.working_dir or workflow_task.working_dir,
        )
        timeout_seconds = command.timeout_seconds or workflow_task.timeout_seconds or 600
        allow_failure = command.allow_failure or workflow_task.allow_failure
        env = {**workflow_task.env, **command.env}

        base_payload = {
            "workflow_id": workflow.id,
            "stage_id": stage_id,
            "stage_index": stage_index,
            "node_id": node.id,
            "workflow_task_id": workflow_task.id,
            "command_id": command_id,
            "command": command.run,
            "cwd": str(cwd),
            "timeout_seconds": timeout_seconds,
            "allow_failure": allow_failure,
        }

        guard_path = command.only_if_path_exists or workflow_task.only_if_path_exists
        if guard_path:
            resolved_guard = _resolve_command_path(cwd, guard_path)
            if not resolved_guard.exists():
                result = {
                    **base_payload,
                    "status": "skipped",
                    "reason": "guard_path_missing",
                    "guard_path": str(resolved_guard),
                }
                self.task_repository.add_event(
                    parent_task["id"],
                    "workflow_command_skipped",
                    "Deterministic workflow command skipped because the guard path is missing.",
                    result,
                )
                return result

        if not cwd.exists():
            result = {**base_payload, "status": "failed", "error": f"Working directory does not exist: {cwd}"}
            self.task_repository.add_event(
                parent_task["id"],
                "workflow_command_failed",
                "Deterministic workflow command failed before execution.",
                result,
            )
            if not allow_failure:
                raise RuntimeError(result["error"])
            return result

        self.task_repository.add_event(
            parent_task["id"],
            "workflow_command_started",
            "Deterministic workflow command started.",
            base_payload,
        )

        started_at = time.monotonic()
        try:
            completed = subprocess.run(
                command.run,
                cwd=str(cwd),
                env={**os.environ, **env},
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration_ms = int((time.monotonic() - started_at) * 1000)
            result = {
                **base_payload,
                "status": "succeeded" if completed.returncode == 0 else "failed",
                "return_code": completed.returncode,
                "duration_ms": duration_ms,
                "stdout": _truncate_text(completed.stdout, 4000),
                "stderr": _truncate_text(completed.stderr, 4000),
            }
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            result = {
                **base_payload,
                "status": "failed",
                "return_code": None,
                "duration_ms": duration_ms,
                "stdout": _truncate_text(exc.stdout or "", 4000),
                "stderr": _truncate_text(exc.stderr or "", 4000),
                "error": f"Command timed out after {timeout_seconds} seconds.",
            }

        artifact = self._write_command_artifact(parent_task, command_id, result)
        if artifact:
            result["artifact_id"] = artifact.get("id")
            result["artifact_path"] = artifact.get("path_or_storage_key")

        if result["status"] == "succeeded":
            self.task_repository.add_event(
                parent_task["id"],
                "workflow_command_succeeded",
                "Deterministic workflow command completed successfully.",
                result,
            )
            return result

        self.task_repository.add_event(
            parent_task["id"],
            "workflow_command_failed",
            "Deterministic workflow command failed.",
            result,
        )
        if not allow_failure:
            raise RuntimeError(f"Workflow command failed: {command.run}")
        return result

    def _write_command_artifact(
        self,
        parent_task: dict[str, Any],
        command_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        safe_command_id = re.sub(r"[^A-Za-z0-9._-]+", "_", command_id).strip("_") or "command"
        task_id = str(parent_task["id"])
        artifact_dir = self.settings.artifact_root / "workflow-command-gates" / task_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{safe_command_id}.log"
        artifact_path.write_text(_render_command_log(result), encoding="utf-8")
        try:
            return self.artifact_repository.create_artifact(
                task_id=task_id,
                artifact_type="workflow_command_log",
                path_or_storage_key=str(artifact_path),
            )
        except Exception as exc:
            self.task_repository.add_event(
                task_id,
                "workflow_command_artifact_failed",
                "Deterministic command log could not be stored as an artifact.",
                {"command_id": command_id, "path": str(artifact_path), "error": str(exc)},
            )
            return None

    def _is_implementation_trigger_stage(self, stage_id: str, nodes: list[WorkflowNode]) -> bool:
        if stage_id in {"implementation-trigger-phase", "implementation-phase"}:
            return True
        for node in nodes:
            role = str(getattr(node, "role", "") or "")
            if role == "implementation_trigger":
                return True
            if node.id in {"implementation-trigger", "implementation-drone"}:
                return True
        return False

    def _trigger_implementation_tasks(
        self,
        task: dict[str, Any],
        *,
        workflow_id: str,
        stage_id: str,
        stage_index: int,
    ) -> list[dict[str, Any]]:
        child_tasks = self.task_repository.list_child_implementation_tasks(str(task["id"]))
        queueable_statuses = {"draft", "review_required", "needs_input", "failed"}
        queued: list[dict[str, Any]] = []
        for child in child_tasks:
            if str(child.get("status") or "") not in queueable_statuses:
                continue
            child_id = str(child.get("id"))
            updated = self.task_repository.update_status(child_id, "queued")
            if updated:
                queued.append(updated)
                self.task_repository.add_event(
                    child_id,
                    "implementation_triggered",
                    "Implementation task was queued by the parent workflow implementation trigger.",
                    {
                        "parent_task_id": task["id"],
                        "workflow_id": workflow_id,
                        "stage_id": stage_id,
                        "stage_index": stage_index,
                    },
                )

        event_type = "implementation_stage_triggered" if queued else "implementation_stage_empty"
        message = (
            f"Implementation trigger queued {len(queued)} stored implementation task(s)."
            if queued
            else "Implementation trigger found no stored implementation tasks to queue."
        )
        self.task_repository.add_event(
            task["id"],
            event_type,
            message,
            {
                "workflow_id": workflow_id,
                "stage_id": stage_id,
                "stage_index": stage_index,
                "task_ids": [child.get("id") for child in queued],
                "found_task_count": len(child_tasks),
            },
        )
        return queued

    def _ordered_workflow_nodes(self, workflow: WorkflowDefinition, first_node_id: Any | None = None) -> list[WorkflowNode]:
        node_map = {node.id: node for node in workflow.nodes}
        ordered: list[WorkflowNode] = []
        seen: set[str] = set()
        for stage in self.workflow_store.build_stages(workflow):
            for node in stage.nodes:
                if node.id not in seen:
                    ordered.append(node)
                    seen.add(node.id)
        for node in node_map.values():
            if node.id not in seen:
                ordered.append(node)
        if first_node_id and str(first_node_id) in node_map:
            selected = node_map[str(first_node_id)]
            return [selected] + [node for node in ordered if node.id != selected.id]
        return ordered

    def _ordered_stage_nodes(
        self,
        workflow: WorkflowDefinition,
        stage_nodes: list[WorkflowNode],
        first_node_id: Any | None = None,
    ) -> list[WorkflowNode]:
        node_ids = {node.id for node in stage_nodes}
        if first_node_id and str(first_node_id) in node_ids:
            selected_id = str(first_node_id)
            return [node for node in stage_nodes if node.id == selected_id] + [
                node for node in stage_nodes if node.id != selected_id
            ]
        return stage_nodes

    def _latest_workflow_resume(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        latest_resume: dict[str, Any] | None = None
        last_stage_started_after_resume = False
        for event in events:
            event_type = str(event.get("event_type") or "")
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            if event_type in ("workflow_resumed", "human_review_confirmed"):
                raw_index = payload.get("resume_stage_index", 1)
                try:
                    resume_stage_index = int(raw_index)
                except (TypeError, ValueError):
                    resume_stage_index = 1
                latest_resume = {"resume_stage_index": resume_stage_index}
                last_stage_started_after_resume = False
            elif latest_resume and event_type == "workflow_stage_started":
                last_stage_started_after_resume = True
        if latest_resume and not last_stage_started_after_resume:
            return latest_resume
        return None

    def _select_skills(self, node: WorkflowNode, task: dict[str, Any]) -> list[str]:
        selected: list[str] = []
        if task.get("assigned_skill"):
            selected.append(str(task["assigned_skill"]))
        selected.extend(node.subagents)
        for workflow_task in node.tasks:
            selected.extend(self._skills_from_workflow_task(workflow_task))
        return sorted({skill for skill in selected if skill})

    def _skills_from_workflow_task(self, workflow_task: WorkflowTask) -> list[str]:
        explicit = getattr(workflow_task, "skills", None)
        if isinstance(explicit, list):
            return [str(skill) for skill in explicit if skill]
        if isinstance(explicit, str) and explicit.strip():
            return [explicit.strip()]
        return [workflow_task.id]

    def _project_lookup(self, task: dict[str, Any], agent_name: str, skill_name: str | None) -> dict[str, Any]:
        if not self.settings.mcp_server_url:
            self.task_repository.add_event(
                task["id"],
                "project_lookup_skipped",
                "MCP server is not configured; workflow execution continues without project-context lookup.",
                {"tool": "project.search"},
            )
            return {"tool": "project.search", "result_count": 0, "result": {}}

        arguments = {
            "query": task.get("topic") or task.get("title"),
            "platform": task.get("target_platform"),
            "peripheral": task.get("topic"),
            "limit": 5,
        }
        return _call_mcp(
            self.settings.mcp_server_url,
            "project.search",
            {
                "agent_name": agent_name,
                "skill_name": skill_name,
                "task_id": task["id"],
                "project_id": task.get("project_id") or "local",
                "arguments": arguments,
            },
        )

    def _build_result_summary(
        self,
        task: dict[str, Any],
        agent_name: str,
        skill_name: str | None,
        lookup: dict[str, Any],
    ) -> str:
        result = lookup.get("result", {})
        if isinstance(result, dict):
            knowledge_count = len(result.get("knowledge") or [])
            rule_count = len(result.get("rules") or [])
            example_count = len(result.get("examples") or [])
            task_count = len(result.get("tasks") or [])
            project_count = len(result.get("projects") or [])
        else:
            project_count = knowledge_count = rule_count = example_count = task_count = 0
        skill_text = f" with skill {skill_name}" if skill_name else ""
        return (
            f"{agent_name}{skill_text} processed '{task.get('title')}' using Supabase project context: "
            f"{project_count} projects, {knowledge_count} knowledge entries, {rule_count} rules, {example_count} examples, "
            f"and {task_count} related tasks."
        )

    def _render_llm_human_review_text(self, plan: dict[str, Any]) -> str:
        lines: list[str] = []
        for iteration in plan.get("iterations", []):
            if not isinstance(iteration, dict):
                continue
            iteration_id = iteration.get("iteration")
            output = str(iteration.get("output") or "")
            lines.append(f"Iteration {iteration_id}")
            lines.append("Response:")
            lines.append(output)
            lines.append("")
        summary = str(plan.get("summary") or "").strip()
        if summary:
            lines.append("Summary:")
            lines.append(summary)
        return "\n".join(lines).strip()


def _call_mcp(base_url: str, tool_name: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, 4):
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
            raise RuntimeError(details) from exc
        except URLError as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt)
    if isinstance(last_error, URLError):
        raise RuntimeError(str(last_error.reason)) from last_error
    raise RuntimeError("MCP call failed")


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truncate_text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


def _resolve_command_path(base: Path, value: str | None) -> Path:
    if not value:
        return base
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return base / candidate


def _render_command_log(result: dict[str, Any]) -> str:
    lines = [
        f"command_id: {result.get('command_id')}",
        f"status: {result.get('status')}",
        f"return_code: {result.get('return_code')}",
        f"cwd: {result.get('cwd')}",
        f"command: {result.get('command')}",
        "",
        "stdout:",
        str(result.get("stdout") or ""),
        "",
        "stderr:",
        str(result.get("stderr") or ""),
    ]
    error = result.get("error")
    if error:
        lines.extend(["", "error:", str(error)])
    return "\n".join(lines).rstrip() + "\n"


def _looks_like_scaffold_request(task: dict[str, Any]) -> bool:
    if str(task.get("workflow_id") or "").strip() == "new_borg_cube_project":
        return True
    text = f"{task.get('title') or ''}\n{task.get('description') or ''}".lower()
    indicators = {
        "create",
        "new project",
        "scaffold",
        "bootstrap",
        "initial",
        "initialize",
        "init ",
        "anlegen",
        "erstellen",
        "neues projekt",
        "projekt erstellen",
        "grundgeruest",
        "grundgerüst",
        "first start",
    }
    return any(indicator in text for indicator in indicators)


def _sandbox_safe_workspace_lines(workspace_path: Any) -> list[str]:
    workspace = _clean_text(workspace_path) or "the target project root"
    return [
        "Workspace write discipline:",
        f"- Claude Code is already running with `{workspace}` as the project workspace.",
        "- Use relative paths from the workspace for reads, writes, and Bash commands.",
        "- Do not create or edit files by prefixing the absolute workspace path.",
        "- For directory creation, use commands like `mkdir -p modules/name` instead of `mkdir -p /workbench/project/modules/name`.",
        "- If a command is blocked by tool approval or sandbox checks, retry once with one simple relative command and report the blocker if it still fails.",
    ]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_temporary_infrastructure_error(exc: Exception) -> bool:
    text = str(exc).lower()
    indicators = (
        "temporary failure in name resolution",
        "name or service not known",
        "nodename nor servname provided",
        "failed to resolve",
        "connection refused",
        "timed out",
    )
    return any(indicator in text for indicator in indicators)


def _responses_similar(left: str, right: str) -> bool:
    normalized_left = _normalize_similarity_text(left)
    normalized_right = _normalize_similarity_text(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= 0.9


def _normalize_similarity_text(value: str) -> str:
    text = value.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return text.strip()


def _is_file_access_blocker_error(exc: Exception) -> bool:
    text = str(exc).lower()
    indicators = (
        "permission denied",
        "operation not permitted",
        "tool approval loop detected",
        "requires approval",
        "[tool_error]",
        "claude code timed out",
        "working directory does not exist",
        "no such file or directory",
        "file not found",
        "cannot access",
        "read-only file system",
        "access is denied",
        "sandbox",
        "blocked by tool approval",
    )
    return any(indicator in text for indicator in indicators)


def _raise_if_tool_approval_loop(output: str) -> None:
    text = output.lower()
    requires_approval_hits = text.count("requires approval")
    tool_error_hits = text.count("[tool_error]")
    if requires_approval_hits >= 2 or (requires_approval_hits >= 1 and tool_error_hits >= 2):
        raise RuntimeError("Tool approval loop detected: repeated '[tool_error] This command requires approval'.")
    if '"finish_reason": "tool_calls"' in text or '"finish_reason":"tool_calls"' in text:
        raise RuntimeError("Tool call loop detected: model returned finish_reason='tool_calls'.")
    if '"tool_calls"' in text and '"arguments": ""' in text and '"name": "bash"' in text:
        raise RuntimeError("Tool call loop detected: Bash tool call emitted with empty arguments.")


def _normalize_spec_path(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("\\", "/").strip("/")
    if not normalized or ".." in Path(normalized).parts:
        return None
    if normalized == "borg-cube.md" or normalized.endswith("/borg-cube.md"):
        return normalized
    return f"{normalized.rstrip('/')}/borg-cube.md"


def _normalize_project_file_path(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("\\", "/").strip("/")
    if not normalized or ".." in Path(normalized).parts:
        return None
    if Path(normalized).is_absolute():
        return None
    blocked_parts = {".git", ".venv", "venv", "__pycache__"}
    if any(part in blocked_parts for part in Path(normalized).parts):
        return None
    return normalized


def _borg_cube_quality_errors(content: str) -> list[str]:
    text = content.strip()
    if not text:
        return ["borg-cube.md is empty"]
    lowered = text.lower()
    required_sections = {
        "metadata": "metadata",
        "goal": "goal",
        "scope": "scope",
        "dependencies": "dependencies",
        "functional requirements": "functional requirements",
        "non-functional requirements": "non-functional requirements",
        "constraints": "constraints",
        "interfaces": "interfaces",
        "assumptions / open points": "assumptions",
    }
    # "problem statement" is optional for some project types, or can be part of goal
    optional_sections = {
        "problem statement": "problem statement",
    }
    
    errors = [
        f"missing section: {label}"
        for label, needle in required_sections.items()
        if needle not in lowered
    ]
    if not re.search(r"(?im)^#\s+\S+", text):
        errors.append("missing top-level markdown title")
    if not re.search(r"(?im)^\s*-\s*FR[-_ ]?\d+", text):
        errors.append("missing traceable FR-* functional requirements")
    if not re.search(r"(?im)^\s*-\s*NFR[-_ ]?\d+", text):
        errors.append("missing traceable NFR-* non-functional requirements")
    return errors


def _spec_type(value: Any, spec_path: str) -> str:
    raw = (_clean_text(value) or "").lower()
    if raw in {"project", "module", "task", "handoff"}:
        return raw
    return "project" if spec_path == "borg-cube.md" else "module"


def _title_from_spec_path(spec_path: str) -> str:
    if spec_path == "borg-cube.md":
        return "Project borg-cube"
    parent = Path(spec_path.replace("\\", "/")).parent
    return parent.name.replace("-", " ").replace("_", " ").title() or "Module borg-cube"


def _map_workbench_path(host_path: str) -> Path | None:
    normalized_host = host_path.replace("\\", "/").rstrip("/")
    if not normalized_host:
        return None
    host_root = os.getenv("WORKBENCH_HOST_ROOT", r"D:\Workbench").replace("\\", "/").rstrip("/")
    container_root = os.getenv("WORKBENCH_CONTAINER_ROOT", "/workbench").replace("\\", "/").rstrip("/")

    if normalized_host.lower() == host_root.lower():
        return Path(container_root)
    prefix = host_root + "/"
    if normalized_host.lower().startswith(prefix.lower()):
        suffix = normalized_host[len(host_root) + 1 :]
        return Path(f"{container_root}/{suffix}") if suffix else Path(container_root)
    if normalized_host.startswith("/"):
        return Path(normalized_host)
    return None
