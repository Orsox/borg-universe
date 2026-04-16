# Feature Specification

## Metadata

| Field | Value |
|---|---|
| Feature Name | Borg Universe Agent Harness |
| Feature ID | borg-universe-agent-harness |
| Status | draft |
| Owner | Borg Collective |
| Primary Area | `BORG/workflows` |
| Last Updated | 2026-04-14 |

## Goal

The root specification defines Borg Universe as an agentic workflow harness. The harness is intended to provide not only individual domain workflows, but also a reusable control layer for intake, planning, disassembly, implementation, validation, Git synchronization, and agent-guided commits.

The goal is a way of working in which specialized agents cooperate like a developer team with different roles: a 
coordinating entry point, clearly separated specialist roles, iterative refinement, deterministic validation, and a traceable Git-based closeout for every change.

## Scope

### In Scope

- Defining a shared agent harness for all workflows under `BORG/workflows`.
- Describing the standard phases for intake, requirements, task disassembly, implementation trigger, implementation, validation, review, and Git closeout.
- Defining a safe Git lifecycle with agent-guided `fetch`, `pull`, diff inspection, and commit generation.
- Positioning the existing workflows `new_borg_cube_project`, `borg-assimilation`, `python_tooling_harness`, and `stm32_nordic_harness` within this shared model.
- Describing the roles of agents, prompts, skills, rules, manifests, and orchestration data.
- Preserving traceability for decisions, assumptions, risks, and validation results.

### Out of Scope

- Full implementation of new workflow YAML files in this change.
- Automatic pushing, merging, rebasing, or force operations against remote branches.
- GUI-driven tool automation such as STM32CubeMX or hardware flashing.
- Fully automatic conflict resolution for Git merges without review.

## Dependencies

- `BORG/workflows/*.yaml` as declarative workflow definitions.
- `BORG/config/orchestration.json` as the execution and agent selection configuration.
- Local or connected models for coordinating and specialized agents.
- Git CLI for repository synchronization, diff inspection, and commit generation.
- Validation tools depending on the harness, for example `pytest`, `compileall`, `cmake`, `make`, or `west`.

### Conceptual References

- Archon-style multi-agent organization with a coordinator, specialist agents, and review loops.
- Tool- and MCP-oriented extensibility, where agents receive capabilities through structured interfaces instead of implicit ad hoc logic.
- A builder pattern with reusable stages for planning, execution, validation, and operational closeout.

## Submodules / Internal Structure

### Root Harness Components

| Path | Purpose |
|---|---|
| `BORG/workflows/new_borg_cube_project.yaml` | Project setup, spec generation, disassembly, and sequential implementation. |
| `BORG/workflows/borg-assimilation.yaml` | Analysis of existing projects, review, and synthesis of cube files without changing source code. |
| `BORG/workflows/python_tooling_harness.yaml` | Harness for Python tools, CLIs, libraries, tests, and host automation. |
| `BORG/workflows/stm32_nordic_harness.yaml` | Harness for STM32 and Nordic projects with deterministic build gates. |
| `BORG/config/orchestration.json` | Agent selection, local model, and global execution parameters. |
| `BORG/agents/` | Descriptions or artifacts for specialized agent roles. |
| `BORG/prompts/` | Reusable prompt building blocks for roles and phases. |
| `BORG/skills/` | Extensible capabilities that agents can invoke deliberately. |
| `BORG/rules/` | Safety and behavior rules for agentic execution. |
| `BORG/manifests/` | Structured descriptions of workflow or agent artifacts. |

### Harness Control Model

The agent harness spans all domain workflows and defines a shared control flow:

1. Intake and scope normalization by a coordinating agent.
2. Requirements and constraint extraction by review or requirement agents.
3. Disassembly into small, verifiable tasks.
4. Sequential or intentionally limited execution by implementation agents.
5. Deterministic validation with project-specific commands.
6. Agent-guided Git closeout with sync, diff summary, and commit.
7. Human review or handoff whenever risks, conflicts, or policy boundaries are reached.

## Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | The root `borg-cube.md` must explicitly describe Borg Universe as a shared agent harness across all workflows. |
| FR-2 | Every workflow under `BORG/workflows` must be mappable to a shared phase model, even if some steps are omitted depending on the domain. |
| FR-3 | The harness must support specialized agent roles for coordination, review, disassembly, implementation, and validation. |
| FR-4 | The harness must support iterative plan-review-refine loops when reviews identify errors, gaps, or open assumptions. |
| FR-5 | The harness must make it traceable which tasks are automated and where human review is required. |
| FR-6 | Before every write-capable work phase, the harness must define a Git sync step that performs at least `git fetch` and evaluates the divergence status of the target branch. |
| FR-7 | Automatic `git pull` may only occur when the branch is clean, the operation is fast-forward capable, and no local conflicts or unreviewed changes are present. |
| FR-8 | If `pull` cannot be performed safely, the harness must trigger a review or conflict-handling step instead and must not apply an implicit merge strategy. |
| FR-9 | After successful implementation and validation, an agent must be able to summarize the diff, generate commit metadata, and produce a structured commit proposal or execute the commit. |
| FR-10 | Agent-guided commits must reference at least the workflow context, the affected subtask, and the validation status. |
| FR-11 | The harness must preserve results, assumptions, risks, and required manual follow-up actions in a compact handoff. |
| FR-12 | The harness must allow new domain workflows to be added without breaking the shared control model. |

## Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Git operations must be safety-oriented by default and must avoid destructive defaults. |
| NFR-2 | Workflow results must be auditable for humans and machine-processable for agents. |
| NFR-3 | The orchestration must be repeatable; similar inputs should produce similarly structured phases and outputs. |
| NFR-4 | Domain-specific validation must be deterministic and adapted to the relevant stack. |
| NFR-5 | The harness should be extendable in a modular way without tightly coupling existing workflows. |
| NFR-6 | The overall process should remain manageable with few parallel tasks and minimize conflict surface area. |

## Constraints

- Repository changes must not silently overwrite unclear or foreign local modifications.
- `git pull` is only allowed as a safe fast-forward or clearly defined sync step; automatic merge commits are not the default.
- Push, rebase, force-push, and branch deletion are not part of the standard harness.
- Hardware-near actions such as flashing or GUI interactions must be explicitly approved outside the standard path.
- The harness description must remain compatible with the current orchestration in `BORG/config/orchestration.json`.

## Interfaces

### Internal Interfaces

| Interface | Purpose |
|---|---|
| Workflow YAML Schema | Declares nodes, tasks, steps, retry rules, and validation commands. |
| Agent Registry | Maps roles such as Queen, Requirement Node, Disassembler, Implementation Drone, or Validator to concrete agents. |
| Prompt and Skill Layer | Provides reusable instructions and capabilities for specialization. |
| Orchestration Config | Provides model selection, endpoints, and global execution limits. |

### External Interfaces

| Interface | Purpose |
|---|---|
| Git CLI | `fetch`, safe `pull`, `status`, `diff`, `add`, and `commit` as the controlled closeout interface. |
| Build and Test Toolchains | Stack-specific validation for Python, CMake, Make, Zephyr/NCS, or additional harnesses. |
| MCP or Tool Connectors | Optional structured tool integration following an Archon-like extension model. |

## Error Handling

| Error Code | Condition | Response |
|---|---|---|
| ERR-GIT-01 | The working tree is not clean before sync or contains foreign changes that cannot be safely classified. | No automatic pull; hand off to a review stage or explicit human review. |
| ERR-GIT-02 | The remote branch is not fast-forward compatible or would create merge conflicts. | Record the fetch result, abort the pull, and hand the conflict path to agent or human review. |
| ERR-GIT-03 | Commit metadata or validation evidence is incomplete. | No commit; route the diff summary and missing evidence back to a review step. |
| ERR-WF-01 | A workflow does not map cleanly to the shared phase model. | Mark the workflow as incomplete and require a root harness adjustment. |
| ERR-VAL-01 | Deterministic validation fails. | No commit; capture findings, logs, and recommended next steps in the handoff. |
| ERR-AGENT-01 | A required agent role, skill, or tool interface is missing. | Fall back to the documented minimal path and mark the open gap in the specification. |

## Assumptions / Open Points

- A dedicated reusable Git harness workflow or shared preflight/postflight library is not yet materialized and should be concretized next under `BORG/workflows` or `BORG/manifests`.
- The current orchestration uses a local model with `max_parallel_tasks: 1`; the specification therefore assumes controlled serial execution by default.
- Archon is used here as a conceptual reference for agent topology and tool integration, not as a system architecture to be reproduced one-to-one.
- Whether agent-guided commits should run automatically by default or first be produced as commit proposals should be decided separately as a policy choice.
