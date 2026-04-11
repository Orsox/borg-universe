---
name: borg-task-decomposer
description: Breaks a borg-cube.md specification into small, independently executable tasks with clear scope and layer separation. Use when a feature spec needs to be converted into a structured task plan.
tools: Read, Grep, Write
---

# Skill — Borg Task Decomposer

## Purpose
Break a specification (`borg-cube.md` + `spec/`) into small executable tasks.

## Responsibilities
- Identify work units from specification sections
- Split large work areas into manageable tasks
- Ensure each task can be executed independently
- Avoid mixing multiple architectural layers

## Output
Creates task files following the project task template.

## Rules
- Prefer many small tasks over a few large ones
- Never invent missing technical facts
- Always reference source spec files