---
name: borg-handover-summary
description: Produce concise feature handovers and PR text. Use after feature implementation and review to summarize changes, affected components, test status, open points, manual checks, deployment notes, and merge or PR descriptions.
---

# Skill - Borg Handover Summary

## Procedure

1. Read Feature Definition, Impact Analysis, Delivery Plan, implementation report, quality report, and validation logs.
2. Summarize what changed and why.
3. List affected components.
4. Report test status with exact commands and outcomes.
5. Capture open points, residual risks, and manual checks.
6. Add deployment, migration, rollback, or configuration notes when relevant.
7. Produce PR or merge text.

## Output Template

```markdown
# Feature Handover

## Change Summary

## Affected Components

## Test Status

## Open Points

## Manual Verification

## Deployment Notes

## PR Description
```

## Rules

- Do not invent successful test results.
- Keep the handover short enough for a PR description.
- Separate completed work from follow-up work.
