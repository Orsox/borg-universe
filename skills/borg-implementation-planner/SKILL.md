---
name: borg-implementation-planner
description: Create dependency-aware implementation plans for new features. Use when a Feature Definition and Impact Analysis need to become concrete work packages with scope, dependencies, Definition of Done, validation commands, and nano-implant implementation prompts.
---

# Skill - Borg Implementation Planner

## Procedure

1. Read the Feature Definition and Impact Analysis.
2. Split the feature into small work packages.
3. Order work packages by dependency.
4. For each package, define scope, affected components, dependencies, Definition of Done, validation commands, and an implementation prompt.
5. Include backend, frontend, database, interfaces, tests, migrations, configuration, templates, and docs only when relevant.
6. Mark blocked packages explicitly.

## Work Package Template

```markdown
## Work Package: <id>

- Title:
- Scope:
- Expected Components:
- Dependencies:
- Definition of Done:
- Validation:
- Status:
- Implementation Prompt:

<nano-implant>
...
```

## Rules

- Keep every package independently reviewable.
- Do not combine unrelated layers unless the change is inseparable.
- Every implementation prompt must begin with `<nano-implant>`.
