from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings
from app.db.repositories import ArtifactRepository, TaskRepository
from app.models.workflows import WorkflowDefinition, WorkflowNode, WorkflowTask
from app.services.local_llm_client import LocalLlmClient, LocalLlmClientError
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
    ) -> None:
        self.task_repository = task_repository
        self.artifact_repository = artifact_repository
        self.settings = settings
        self.workflow_store = workflow_store or WorkflowStore(settings.workflows_root)
        self.orchestration_store = orchestration_store or OrchestrationSettingsStore(settings.borg_root)
        self.local_llm_client = local_llm_client

    def process_next_batch(self) -> int:
        tasks = self.task_repository.list_by_status("queued", self._queue_parallelism())
        for task in tasks:
            self.process_task(task)
        return len(tasks)

    def process_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = task["id"]
        agent_name = task.get("assigned_agent") or "mock-agent"
        skill_name = task.get("assigned_skill")
        try:
            initial_events = self.task_repository.list_events(task_id)
            resume_context = self._latest_workflow_resume(initial_events)
            self.task_repository.update_status(task_id, "running")
            self.task_repository.add_event(
                task_id,
                "agent_started",
                f"Worker assigned task to {agent_name}.",
                {"agent_name": agent_name, "skill_name": skill_name, "workflow_id": task.get("workflow_id")},
            )
            if resume_context:
                review_context = self._latest_review_context(initial_events)
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
            if task.get("workflow_id"):
                self.task_repository.add_event(
                    task_id,
                    "workflow_started",
                    "Worker started the selected workflow after local LLM processing.",
                    {"workflow_id": task.get("workflow_id"), "agent_name": agent_name, "llm_plan": llm_plan},
                )
                self._run_workflow(
                    task,
                    agent_name,
                    llm_plan,
                    stage_index=resume_context.get("resume_stage_index", 0) if resume_context else 0,
                )
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

        orchestration = self.orchestration_store.load()
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

        orchestration = self.orchestration_store.load()
        client = self.local_llm_client or LocalLlmClient(orchestration.local_model)
        prompt = self._llm_review_resume_prompt(task, review_context, stage_index)
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
        lines = [
            "You are resuming an agentic workflow after human review.",
            "The workflow stage is already selected by the system; do not choose or change the first node.",
            "Use the human review notes as authoritative input for the next workflow level.",
            "Return a concise implementation handoff with risks, required file actions, and verification steps.",
            f"Next workflow level: {stage_index + 1}",
            f"Title: {task.get('title')}",
            f"Description: {task.get('description')}",
            f"Local path: {task.get('local_path')}",
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
            elif event_type == "review_confirmed" and payload.get("notes"):
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
    ) -> None:
        workflow_id = task.get("workflow_id")
        if not workflow_id:
            return

        try:
            workflow = self.workflow_store.get_workflow(str(workflow_id))
        except WorkflowStoreError as exc:
            self.task_repository.add_event(
                task["id"],
                "workflow_unavailable",
                "Selected workflow could not be loaded.",
                {"workflow_id": workflow_id, "error": str(exc)},
            )
            return
        if not workflow:
            self.task_repository.add_event(
                task["id"],
                "workflow_unavailable",
                "Selected workflow was not found.",
                {"workflow_id": workflow_id},
            )
            return

        stages = self.workflow_store.build_stages(workflow)
        if not stages:
            return

        bounded_stage_index = min(max(stage_index, 0), len(stages) - 1)
        stage = stages[bounded_stage_index]
        stage_id = workflow.steps[bounded_stage_index].id if bounded_stage_index < len(workflow.steps) else stage.title
        nodes = self._ordered_stage_nodes(workflow, stage.nodes, llm_plan.get("first_node_id"))
        self.task_repository.add_event(
            task["id"],
            "workflow_stage_started",
            f"Workflow level {bounded_stage_index + 1} started: {stage.title}.",
            {
                "workflow_id": workflow.id,
                "stage_id": stage_id,
                "stage_index": bounded_stage_index,
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
                    "stage_index": bounded_stage_index,
                },
            )

        for index, node in enumerate(nodes, start=1):
            agent_name = node.agent or default_agent_name
            selected_skills = self._select_skills(node, task)
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
                    "stage_index": bounded_stage_index,
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
                    "stage_index": bounded_stage_index,
                },
            )
        self.task_repository.add_event(
            task["id"],
            "workflow_stage_completed",
            f"Workflow level {bounded_stage_index + 1} completed: {stage.title}.",
            {
                "workflow_id": workflow.id,
                "stage_id": stage_id,
                "stage_index": bounded_stage_index,
                "stage_title": stage.title,
                "next_stage_index": bounded_stage_index + 1 if bounded_stage_index + 1 < len(stages) else None,
            },
        )

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
            if event_type == "workflow_resumed":
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
