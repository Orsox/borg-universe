---
name: borg-cube-inspector
description: Validates and inspects existing borg-cube.md files for structural correctness, missing sections, and wording conventions. Use when reviewing or normalizing an already existing feature specification.
tools: Read, Grep
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

## Required section structure

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
