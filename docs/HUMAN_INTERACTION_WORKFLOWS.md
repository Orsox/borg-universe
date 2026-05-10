# Human Interaction Workflows

Workflow pauses use three distinct human-interaction modes.

## Review Required

Use Review Required only when the developer must approve, reject, or decide on a broader set of planned changes.

Output shape:

```text
Review Required

Planned Changes
- Update the queue scheduler to reject new messages when the ring buffer is full.
- Add tests for overflow behavior and scheduler startup logging.

Review Questions
- Do we want queue overflow to reject new messages instead of dropping the oldest messages?
- Should scheduler startup logging block boot on EPC611 read failure, or only warn?
```

Rules:
- Use English.
- Show only Planned Changes and Review Questions.
- Keep questions concrete, answerable, and tied to the planned changes.
- Do not show summaries, raw model transcripts, internal reasoning, or cube previews.

## Question Step

Use Question Step when the workflow only needs a targeted answer and no broader review is required.

Output shape:

```text
Question Step

Context
- Startup logging location is not specified.

Questions
- Should the EPC611 version be logged before or after scheduler start?
```

`Context` is optional and should stay short.

## No Review Needed

When no approval or targeted answer is needed, the workflow should continue without rendering a human-facing review or question block.
