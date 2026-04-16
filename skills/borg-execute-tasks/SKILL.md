---
name: borg-execute-tasks
description: Executes tasks sequentially from a structured task list file, respecting dependencies and constraints. Use when the user asks to implement, run, or process a prepared task plan inside an approved task workspace.
tools: Read, Glob, Grep, Write, Edit, Bash
disable-model-invocation: true
context: fork
agent: general-purpose
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

Use the borg-implementation-drone.

Target:
$ARGUMENTS

Steps:
1. Read task list
2. Read spec
3. Confirm the task workspace metadata is present and scoped to exactly one approved task
4. Execute the highest priority runnable task only
5. Update tasks
6. Write implementation report

Constraints:
- no guessing
- no redesign
- no scope expansion
- no merge or branch integration actions
- no execution outside the prepared task worktree
