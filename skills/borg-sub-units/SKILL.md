---
name: borg-sub-units
description: Manages Borg subunits by updating borg-cube.md with submodule metadata, entry points, and dependencies. Use when scripts or modules within a feature need to be registered or documented in the feature spec.
tools: Read, Grep, Write, Edit
---

# Skill: borg-sub-units

This skill manages Borg subunits by updating the `borg-cube.md` file and ensuring submodules in a `borg-cube.md`
directory are properly documented.

## When to Use

TRIGGER when:

- User asks to update, create, or manage borg-cube.md files
- User mentions "borg-sub-units" or "submodule"
- User wants to add/verify submodule documentation in borg-cube.md files

DO NOT TRIGGER when:

- User asks general questions about Borg modules without subunits
- User is working on code that doesn't involve borg-cube.md updates

## What This Skill Does

1. **Finds all script/moudules in the module ** in the project under the $ARGUMENTS[0]
2. **Identifies script/moudules ** by scanning the $ARGUMENTS[0] directory containing the borg-cube.md file
3. **Updates the borg-cube.md file** with a "Submodules" section
    - Position: After `## Dependencies` if present, otherwise after `## Out of Scope`
    - Before the next `---` separator
4. **Validates script/moudules documentation** to ensure all subdirectories are properly referenced
5. **Gives a dependency description** of the underlying scripts

## Output Format

When updating a borg-cube.md file, the skill adds/updates:

```markdown
## Submodules

- `<module_name>`: `<purpose_from_metadata_or_inference>`
```

## Key Files

| File                            | Purpose                                     |
|---------------------------------|---------------------------------------------|
| `borg/*/borg-cube.md`           | Feature specification files for each module |


## Example Interactions

**User**: "Update the borg-cube.md with all subunits"
**Skill**: Scans directories, identifies scripts or files, adds Submodules section

**User**: "Check if metrics.py script is documented in multi_llm"
**Skill**: Verifies documentation and adds missing entries

**User**: "Check if metrics.py script is documented in multi_llm"
**Skill**: Verifies documentation and adds missing entries
