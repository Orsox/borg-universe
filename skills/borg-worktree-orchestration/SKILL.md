---
name: borg-worktree-orchestration
description: Prepares and finalizes Git worktrees for Claude Code workflow phases. Use when a workflow node writes repo files, needs reproducible retries, or must isolate implementation work from the shared repository.
tools: Read, Grep, Bash
---

# Skill — Borg Worktree Orchestration

Use this skill whenever a Claude Code workflow phase needs isolated repo state.

## Use cases

- architecture runs that materialize specs or scaffolding
- implementation tasks that change code, tests, or docs
- retry flows that must preserve earlier failed states
- validation or review flows that depend on a known branch and commit

Do not use this skill for:

- read-only review
- database-only persistence
- side-effect-free task disassembly

## Required metadata

Track these fields for every prepared workspace:

- `workspace_id`
- `workflow_id`
- `task_id`
- `node_id`
- `branch_name`
- `worktree_path`
- `base_commit`
- `head_commit`
- `lifecycle_state`

## Branch patterns

- architecture: `queen/<workflow-id>/architecture-v<retry>`
- implementation: `impl/<task-id>`
- integration candidate: `integration/<workflow-id>/<candidate-id>`

## Worktree patterns

- architecture: `.worktrees/<workflow-id>/queen-architecture-v<retry>`
- implementation: `.worktrees/impl/<task-id>`

## Standard procedure

Use the helper script `skills/borg-worktree-orchestration/manage_worktree.sh` for all Git operations to ensure consistency and proper error handling.

### 1. Prepare

- Call: `./skills/borg-worktree-orchestration/manage_worktree.sh prepare <workflow_id> <branch_name> <worktree_path> <base_commit>`
- Stores workspace metadata in `<worktree_path>/.borg-workspace.json`.

### 2. Run domain agent

- Architecture agents may write specs and scaffold files inside the worktree.
- Review agents remain read-only by default.
- Implementation agents may edit, test, and commit only inside the assigned worktree.

### 3. Finalize

- Call: `./skills/borg-worktree-orchestration/manage_worktree.sh finalize <worktree_path> <state>`
- Transition workspace state to `reviewable`, `archived`, or `discarded`.

### 4. Sync / Merge (New)

- Call: `./skills/borg-worktree-orchestration/manage_worktree.sh sync <branch_name> <target_branch>`
- Safely merges changes from an isolated branch into a target branch (e.g. `main`).

### 5. Cleanup

- Call: `./skills/borg-worktree-orchestration/manage_worktree.sh cleanup <worktree_path>`
- Removes the worktree and prunes the Git state.

## Guardrails

- never let feature agents merge branches
- never delete dirty worktrees silently
- never reuse a task worktree for a different task
- never mutate the shared workspace when an isolated worktree was requested
