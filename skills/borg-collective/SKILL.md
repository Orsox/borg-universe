---
name: borg-collective
description: Collects relevant feature context by locating and reading borg-cube.md files. Use when implementing, reviewing, or testing a feature to gather its specification, source files, tests, and dependencies before starting work.
tools: Read, Grep, Glob
---

# collect_feature_context

You collect the relevant implementation context for a feature.

Your primary source of truth is a file named `borg-cube.md`.
Each feature is expected to have its own `borg-cube.md` file containing the feature specification.

## Purpose

Use this skill to:
- identify the relevant feature directory
- locate the corresponding `borg-cube.md`
- extract the feature requirements and constraints
- identify the source files, tests, interfaces, and dependencies related to that feature
- provide a compact working context for implementation, refactoring, review, or testing

## Primary rule

Treat `borg-cube.md` as the primary feature specification if it exists.

Do not ignore it.
Do not start implementation before checking whether a relevant `borg-cube.md` exists.

## When to use

Use this skill when:
- the user asks to implement a feature
- the user asks to change behaviour of an existing feature
- the user asks for tests for a feature
- the user asks for a review of a feature
- the user asks to understand a feature
- a task mentions a module, feature name, or feature directory

## When NOT to use

Do not use this skill when:
- the task is clearly unrelated to a specific feature
- the task is purely global infrastructure with no feature-level specification
- the task is only about formatting, spelling, or documentation outside feature scope

## Expected workflow

1. Identify the feature name, directory, or module mentioned in the task.
2. Search for the nearest relevant `borg-cube.md`.
3. Read and summarize the specification.
4. Identify the files that implement or test that feature.
5. Return a compact structured context.

## Search strategy

When looking for `borg-cube.md`:
- first check the directory of the mentioned module or feature
- then check parent directories
- then check likely feature directories nearby
- prefer the nearest matching `borg-cube.md`

If multiple `borg-cube.md` files exist:
- prefer the one closest to the affected code
- mention other possibly relevant spec files if they may influence the task

## What to extract from borg-cube.md

Extract at least:
- feature goal
- functional requirements
- non-functional requirements
- constraints
- interfaces
- acceptance criteria
- open questions or assumptions
- explicitly mentioned files, modules, APIs, protocols, or tests

## Output format

Return the result in this format:

### Feature context
- Feature: <name>
- Spec file: <path to borg-cube.md>
- Feature directory: <path>
- Confidence: <high|medium|low>

### Specification summary
- Goal: ...
- Key requirements:
  - ...
  - ...
- Constraints:
  - ...
  - ...
- Acceptance criteria:
  - ...
  - ...

### Relevant implementation files
- <path>
- <path>

### Relevant test files
- <path>
- <path>

### Dependencies / interfaces
- <path or module>
- <path or module>

### Notes
- assumptions
- ambiguities
- missing information

## Important behaviour rules

- Be concise but complete.
- Prefer file paths over vague descriptions.
- Do not modify code while using this skill.
- Do not invent requirements that are not supported by `borg-cube.md` or nearby code.
- If no `borg-cube.md` is found, explicitly say so and fall back to code structure analysis.
- If the spec and implementation conflict, mention the conflict clearly.

## Fallback behaviour

If no `borg-cube.md` exists:
- infer the feature boundaries from directory structure, module names, README files, and tests
- state clearly that the feature spec file is missing
- list the most likely files that define behaviour

## Example intent

User task:
"Implement logging for the vehicle detection feature"

Expected behaviour:
- find the relevant feature directory
- locate `borg-cube.md`
- extract logging-related or behavioural constraints
- identify relevant implementation and test files
- provide context before implementation starts
