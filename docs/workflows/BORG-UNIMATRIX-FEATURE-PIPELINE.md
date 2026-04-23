# BORG-UNIMATRIX-FEATURE-PIPELINE

## Purpose

`BORG-UNIMATRIX-FEATURE-PIPELINE` is the dedicated Borg workflow for implementing new features or new functionality end to end. It turns a rough idea into a Feature Definition, analyzes project impact, plans delivery packages, executes scoped implementation work, reviews quality, and produces a handover.

Use this workflow instead of the older workflows when the target is a product or code feature. Do not use it for project assimilation, borg-cube generation, workflow generation, or narrow repair-only work.

## When To Use

Use the pipeline for:

- New user-facing features
- New backend or API functionality
- New UI workflows
- New data-backed behavior
- Cross-cutting changes that need impact analysis and delivery planning

Prefer existing workflows for:

- `borg-assimilation`: scanning an existing project and generating Borg specifications
- `new_workflow_harness`: creating or reviewing workflow infrastructure
- `borg-nanoprobe-repair`: targeted repair of an existing broken area
- `new_borg_cube_project`: creating borg-cube project scaffolding

## Inputs

- Feature idea or requirement
- Optional issue, task, design note, or user story
- Optional constraints such as deadline, compatibility, security, target users, or rollout needs

## Phases

1. **Feature Intake**: `borg-intake-drone` creates a compact Feature Definition with goal, value, scope, non-goals, risks, dependencies, missing information, and assumptions.
2. **Discovery and Impact Analysis**: `borg-impact-drone` maps affected modules, services, APIs, UI, data models, tests, documentation, configuration, and migrations.
3. **Delivery Planning**: `borg-planning-drone` creates small work packages with dependencies, Definition of Done, validation commands, and `<nano-implant>` implementation prompts.
4. **Implementation**: `borg-git-orchestrator` prepares and finalizes isolated workspaces; `borg-implementation-drone` executes one approved package at a time.
5. **Review and Quality Gate**: `borg-review-drone` checks architecture fit, naming, test coverage, side effects, breaking changes, docs, migrations, configuration, and manual checks.
6. **Handover**: `borg-handover-drone` summarizes changes, affected components, test status, open points, deployment notes, and PR text.

## Outputs

- Feature Definition
- Impact Analysis
- Delivery Plan with work packages
- Implementation report per work package
- Quality Gate Report
- Feature Handover with PR or merge text

## Example Request

```text
Run BORG-UNIMATRIX-FEATURE-PIPELINE for this feature:
Add project-level labels so tasks can be filtered by label in the UI and API.
Labels should be stored with tasks, visible on the task detail page, and usable
from the task list filters. Keep the first version single-select.
```

## Example Workflow Invocation

Use workflow id:

```text
BORG-UNIMATRIX-FEATURE-PIPELINE
```

Workflow file:

```text
BORG/workflows/borg-unimatrix-feature-pipeline.yaml
```

With task description:

```text
Feature: Add project-level labels for tasks.
Goal: Filter and display tasks by one label.
Constraints: preserve existing task list behavior and add tests for repository and UI paths.
```

## Reused Building Blocks

- `borg-git-orchestrator`: workspace lifecycle and branch/worktree metadata
- `borg-implementation-drone`: deterministic execution of approved implementation tasks
- `borg-acceptance-criteria-writer`: acceptance-signal support during intake
- `borg-blocker-extractor`: missing-information and blocker detection
- `borg-module-cataloger`: repository/module discovery
- `borg-task-decomposer`: package decomposition
- `borg-dependency-mapper`: dependency ordering
- `borg-test-mock-unit-reviewer`: test-quality review support

## New Building Blocks

- `borg-intake-drone` with `borg-feature-intake`
- `borg-impact-drone` with `borg-impact-analysis`
- `borg-planning-drone` with `borg-implementation-planner`
- `borg-review-drone` with `borg-quality-gate`
- `borg-handover-drone` with `borg-handover-summary`
- `borg-change-execution` for feature implementation discipline; it complements the existing `borg-execute-tasks` skill and can be attached to implementation agents that need feature-specific execution rules.

## Assumptions

- Workflows are discovered automatically from `BORG/workflows/*.yaml`.
- Agent definitions are stored in `agents/`.
- Reusable skills are stored in `skills/<skill-name>/SKILL.md`.
- The current implementation agent remains the canonical executor for planned code changes, so the new workflow reuses it instead of creating a duplicate implementation agent.
