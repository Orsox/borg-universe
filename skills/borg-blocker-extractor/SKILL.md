---
name: borg-blocker-extractor
description: Identifies missing information, uncertainties, and blockers in specifications. Use when a spec or borg-cube.md has gaps, unclear requirements, or unresolved hardware/software dependencies.
tools: Read, Grep, Write
---

# Skill — Borg Blocker Extractor

## Purpose
Identify missing information, uncertainties, and blockers in specifications.

## Responsibilities
- Detect missing register definitions
- Detect unclear sequencing requirements
- Identify incomplete hardware information

## Output
Write entries to:

- `reviews/open-questions.md`
- `reviews/blockers.md`

## Rules
Never guess undocumented behaviour.
Always surface uncertainty explicitly.