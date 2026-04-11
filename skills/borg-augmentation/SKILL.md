---
name: borg-augmentation
description: Augments an existing specification and generates a downstream handoff for task planning. Use when a borg-cube.md or spec needs to be enriched with missing details before task decomposition.
tools: Read, Grep, Write, Edit
disable-model-invocation: true
context: fork
agent: general-purpose
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

Use the `borg-spec-augmentation` subagent workflow to augment the provided specification.

Target:
$ARGUMENTS

Your job:
1. Read the target spec and nearby supporting files if relevant.
2. Improve the spec without replacing its original intent.
3. Add missing implementation-relevant detail.
4. Generate the mandatory handoff file at:
   `handoffs/<spec-base-name>.augmentation-handoff.md`
5. Ensure the handoff is strong enough for a downstream task agent to create or update tasks.

Important constraints:
- Preserve original structure where practical.
- Mark uncertainties explicitly.
- Strengthen acceptance criteria.
- Document task impact, test impact, risks, assumptions, and open questions.
- Do not invent product intent.
- Prefer minimal but high-value augmentation.

At the end, report:
- which files were changed
- where the handoff was written
- whether the result is task-ready