---
name: borg-dependency-mapper
description: Determines the correct execution order for generated tasks by detecting logical dependencies between them. Use when a task list needs to be sequenced or dependency chains need to be established.
tools: Read, Grep, Write, Edit
---

# Skill — Borg Dependency Mapper

## Purpose
Determine the correct order of execution for generated tasks.

## Responsibilities
- Detect logical dependencies between tasks
- Create dependency chains
- Prevent invalid execution order

## Examples
Typical dependencies:

HAL → Transport → Register Layer → Control → Acquisition → Algorithms

## Output
Updates task files and `tasks/task-index.md` with dependency references.