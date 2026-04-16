---
name: borg-execute-tasks
description: Executes tasks sequentially from a structured task list file, respecting dependencies and constraints. Use when the user asks to implement, run, or process a prepared task plan.
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
3. Execute highest priority tasks
4. Update tasks
5. Write implementation report

Constraints:
- no guessing
- no redesign
- no scope expansion