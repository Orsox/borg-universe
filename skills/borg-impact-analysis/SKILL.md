---
name: borg-impact-analysis
description: Analyze repository impact for a planned feature. Use when Codex needs to discover affected modules, services, APIs, UI areas, data models, tests, docs, migrations, configuration, risks, side effects, and architecture implications before planning implementation.
---

# Skill - Borg Impact Analysis

## Procedure

1. Read the Feature Definition.
2. Map keywords to repository files with `rg` and `rg --files`.
3. Inspect likely modules, services, APIs, UI templates, models, tests, config, migrations, docs, and workflow files.
4. Identify existing conventions, helper APIs, validation commands, and reusable patterns.
5. Classify risks as architecture, compatibility, data, security, test, operations, or UX risks.
6. Produce a recommended implementation strategy with open questions and assumptions.

## Output Template

```markdown
# Impact Analysis

## Affected Areas

## Existing Patterns To Reuse

## Risks And Side Effects

## Architecture Implications

## Recommended Strategy

## Open Questions

## Assumptions
```

## Rules

- Prefer file evidence over speculation.
- Include tests and documentation in the impact map.
- Do not edit source files during impact analysis.
