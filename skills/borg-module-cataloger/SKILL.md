---
name: borg-module-cataloger
description: Scans an existing project to identify maintained modules in active use and map them to root and module borg-cube.md specifications. Use when a project-wide assimilation needs module boundaries, spec paths, and agent-facing cross-references.
tools: Read, Glob, Grep
disable-model-invocation: true
---

Use this skill when a repository must be described through a root `borg-cube.md` and a set of module `borg-cube.md` files.

## Purpose

Identify which maintained modules are actually used by the project, then provide a stable module inventory for specification writing.

## Workflow

1. Inventory source-bearing directories, entry points, and configuration files.
2. Ignore caches, virtual environments, generated output, vendor trees, `.git`, `.idea`, and similar tool metadata unless the repository clearly maintains them as source.
3. Determine module boundaries from maintained package or component directories, not from every individual file.
4. Confirm module relevance through imports, registrations, configuration wiring, command entry points, or test consumers.
5. Produce safe relative spec paths ending with `borg-cube.md`.
6. Feed the root `borg-cube.md` with agent-facing references to every generated module spec.

## Boundary Heuristics

- Python: Prefer package directories under `src/`, `app/`, `services/`, `models/`, `api/`, or similar source roots.
- JavaScript/TypeScript: Prefer `apps/`, `packages/`, `src/features/`, `src/lib/`, or other maintained component folders.
- C/C++/Embedded: Prefer maintained driver, service, protocol, board-support, or domain module directories. Exclude vendor SDKs, generated HAL code, and build output unless explicitly owned.
- Mixed repositories: Group by maintained responsibility boundary so each module spec stays coherent and useful.

## Root Spec Requirements

In `Submodules / Internal Structure`, list each generated module spec with:

- the relative spec path
- a one-line responsibility summary
- the dependency, consumer, or entry-point relationship proving relevance
- a short cue telling downstream agents when to open that module spec

Preferred bullet shape:

- `path/to/borg-cube.md`: Handles `<responsibility>`. Used by `<consumer or entry point>`. Open when working on `<task area>`.

## Rules

- Only describe code; never request or imply code changes in this step.
- If evidence for a boundary is weak, keep the module merged into a higher-level maintained directory and note the uncertainty as an assumption.
- Keep the root project spec coarse and move detailed behavior into module specs.
- Ensure every module referenced in the root spec has a corresponding generated module spec.
