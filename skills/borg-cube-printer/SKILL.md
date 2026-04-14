---
name: borg-cube-printer
description: Creates new borg-cube.md files from scratch using the canonical template. Use when a feature or module needs a fresh specification file written from a template.
tools: Read, Write
disable-model-invocation: true
---

Use this skill as authoritative reference material for generating and editing `borg-cube.md` files.

## Canonical purpose

A `borg-cube.md` is the implementation-facing feature/module specification for a single feature or module.
It must be:
- structured
- internally consistent
- grounded in evidence
- testable
- maintainable

For the `new_borg_cube_project` workflow, the root `borg-cube.md` is both a stored database spec and a materialized project file. Module specs should also be materialized under safe relative module paths such as `src/package/borg-cube.md` or `module-name/borg-cube.md`.

## Required section structure

< Use the reference/borg-cube-template.md file >

1. Feature Specification title
2. Metadata
3. Goal
4. Problem Statement
5. Scope
6. Dependencies
7. Submodules / internal structure if known
8. Functional Requirements
9. Non-Functional Requirements
10. Constraints
11. Interfaces
12. External API / request-response schema if applicable
13. Error handling expectations if applicable
14. Assumptions / open points if evidence is incomplete

## New project output

When the caller is creating a new Borg Cube project:

- Set `materialize_borg_cube_files` to `true`
- Return `borg_cube_specs` for the project and modules
- Return `project_files` for the smallest useful scaffold when the target project is empty
- Ensure the root `borg-cube.md` contains the canonical sections from this skill
- Include traceable `FR-*` functional requirements and `NFR-*` non-functional requirements
- Use relative paths only
- Keep scaffold files text-only and directly relevant to the selected project type
- Prefer pure Python scaffolds for Python tooling requests
- Do not add embedded build systems unless the request is explicitly embedded

## Writing rules

- Use precise engineering English
- Prefer `shall` for requirements
- Keep requirements atomic and testable
- Distinguish observed facts from inferred behavior
- Mark assumptions explicitly
- Avoid vague terms unless defined
- Keep naming consistent across all sections
- If output is structured, define its schema
- If configuration exists, document types, defaults, and requiredness
- If error behavior exists, describe failure modes clearly
- Avoid incomplete sections and dangling examples

## Terminology normalization

Use one preferred term per concept.
Do not alternate casually between:
- output / result / response / payload
- dispatcher / client / service unless they are distinct modules
- timeout_seconds vs timeout_ms unless intentionally different

## Requirement quality rules

A requirement is acceptable only if it is:
- singular
- unambiguous
- testable
- feasible
- traceable to the module goal and scope

Weak phrases that must be tightened:
- clear
- structured
- reliable
- scalable
- suitable for
- confidence-like
- safely
- appropriate
- if available

## Minimum interface expectations

If a module has:
- config -> describe config keys, types, defaults, validation
- structured output -> define fields
- API endpoint -> define request and response
- batch behavior -> define partial failure behavior
- timeout -> define unit
- dependency on another module -> describe contract or at least interaction boundary
