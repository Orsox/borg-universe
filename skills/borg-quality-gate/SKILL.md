---
name: borg-quality-gate
description: Review implemented feature changes for quality gates. Use when a feature diff must be checked for architecture fit, naming, convention usage, test coverage, side effects, breaking changes, docs, migrations, config, security, and manual verification needs.
---

# Skill - Borg Quality Gate

## Procedure

1. Read the Feature Definition, Impact Analysis, Delivery Plan, diff, build/compilation status, and test results.
2. Check whether implementation matches the planned scope and compiles without errors.
3. Review architecture fit, naming, conventions, error handling, and compatibility.
4. Verify tests cover new behavior, edge cases, and failure paths where relevant.
5. Check docs, migrations, configuration, and templates when changed or expected.
6. Identify breaking changes, side effects, and release risks.
7. Produce the Quality Gate Report.

## Output Template

```markdown
# Quality Gate Report

## Findings

## Build/Compilation Status

## Required Fixes

## Test Coverage

## Residual Risks

## Manual Verification

## Decision
```

## Rules

- Findings come first and are ordered by severity.
- Do not mark the gate as passed when required validation did not run.
- Use `retry_required: true` when blockers require another implementation pass.
