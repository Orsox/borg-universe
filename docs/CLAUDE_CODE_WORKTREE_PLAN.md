# Claude Code Worktree Plan

## Goal

Introduce an explicit Git and workspace orchestration layer between workflow control and domain agents so Claude Code runs stay reproducible, isolated, and reviewable.

## Target Operating Model

- `borg-git-orchestrator` owns branches, worktrees, commit boundaries, cleanup, and lifecycle state.
- `borg-queen-architect` produces architecture and spec outputs inside a prepared architecture worktree.
- `borg-requirement-node` reviews prepared outputs in read-only mode and emits structured correction lists instead of directly fixing repo files.
- `borg-disassembler` stays side-effect-light and emits task objects plus workspace requirements.
- `borg-implementation-drone` executes exactly one approved task inside a prepared task worktree and never merges.
- Integration and cleanup remain centralized and auditable.

## Lifecycle Model

Each workspace record should carry at least:

- `workspace_id`
- `workflow_id`
- `task_id`
- `node_id`
- `branch_name`
- `worktree_path`
- `base_commit`
- `head_commit`
- `lifecycle_state`

Recommended `lifecycle_state` values:

- `prepared`
- `active`
- `reviewable`
- `approved`
- `merged`
- `discarded`
- `archived`

## Branch and Path Naming

- Architecture run: `queen/<workflow-id>/architecture-v<retry>`
- Architecture worktree: `.worktrees/<workflow-id>/queen-architecture-v<retry>`
- Implementation task: `impl/<task-id>`
- Implementation worktree: `.worktrees/impl/<task-id>`
- Optional integration review: `integration/<workflow-id>/<candidate-id>`

## Claude Code Agent Changes

### `borg-git-orchestrator`

- Prepare architecture worktrees with base branch and base commit metadata.
- Prepare implementation task worktrees with one branch per task.
- Finalize worktrees by capturing `git status`, `head_commit`, test outcome, and cleanup decision.
- Lock retained worktrees and prune removed entries only through centralized policy.

### `borg-queen-architect`

- Assume a prepared workspace instead of deciding Git behavior ad hoc.
- Materialize files only inside the assigned architecture worktree.
- Emit spec metadata needed by review and retry handling.
- Request retries through a new architecture worktree revision rather than mutating a prior one in place.

### `borg-requirement-node`

- Operate read-only on architecture outputs by default.
- Return correction lists and review verdicts, not direct repo edits.
- Escalate only when a workflow explicitly allows materialized review fixes.

### `borg-implementation-drone`

- Require prepared implementation workspace metadata as input.
- Stay confined to one task, one worktree, one commit boundary where feasible.
- Never merge, rebase, or clean up foreign worktrees.
- Write handoff data that allows the orchestrator to finalize or archive the workspace.

## Claude Code Skills

### New skill: `borg-worktree-orchestration`

Use for:

- preparing architecture and implementation worktrees
- recording workspace metadata
- enforcing branch naming and lifecycle transitions
- finalizing, locking, or removing worktrees safely

### Updated skill: `borg-execute-tasks`

Add:

- prerequisite check for prepared worktree metadata
- single-task execution contract
- explicit ban on merge and branch integration actions

## Workflow Node Changes

Add infrastructure nodes around file-writing phases:

1. `git-prepare-architecture`
2. `workflow-architect`
3. `git-finalize-architecture`
4. `workflow-review`
5. `git-prepare-implementation-task`
6. `implementation-drone`
7. `git-finalize-implementation-task`
8. optional `integration-review`

Retry rule:

- review failures create a new architecture worktree revision
- previous failed worktrees remain available until the replacement run is validated

## Suggested Delivery Order

1. Add the Git/worktree orchestrator agent and worktree skill.
2. Update architecture, review, and implementation agents to use the new boundary.
3. Add workspace metadata fields to workflow/task persistence.
4. Update workflow YAMLs with `git-*` nodes and retry semantics.
5. Extend Claude Code workspace sync so project-local `.claude` assets include the new agent and skill.
6. Add audit logging for workspace preparation, finalization, lock, prune, and cleanup outcomes.

## Guardrails

- No direct work on `main`.
- Reviewer defaults to read-only.
- Implementation agents may commit but may not merge.
- Cleanup runs only through the orchestrator.
- Every retained workspace must have a lifecycle state and reason.

## Open Follow-Ups

- Add worker/runtime support for workspace metadata persistence.
- Decide whether architecture outputs commit automatically or only when marked reviewable.
- Define integration reviewer and merge policy once task-level isolation is stable.
