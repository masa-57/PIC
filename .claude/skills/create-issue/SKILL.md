---
name: create-issue
description: Create a standardized GitHub issue. Pass type and title as arguments (e.g., /create-issue bug: Modal timeout on large batches).
---

# Create GitHub Issue

Create a well-formatted GitHub issue in `masa-57/NIC` with consistent structure and auto-labeling.

## Arguments

The user provides `type: title` where type is one of:
- `bug` — Bug report (label: `bug`)
- `feature` — Feature request (label: `enhancement`)
- `docs` — Documentation (label: `documentation`)
- `security` — Security issue (label: `security`)

Example: `/create-issue bug: Modal timeout on large batches`

If no arguments are provided, ask the user for the type and title.

## Procedure

1. **Parse arguments** — Extract the type and title from the user's input. If the type is not one of the valid types above, ask the user to clarify.

2. **Gather context** — Based on the conversation history and title, determine:
   - **Problem**: What is the issue? (1-3 sentences)
   - **Proposed fix**: How should it be resolved? (bullet points, or "TBD" if unknown)
   - **Affected files**: Which files are involved? (list file paths, or "TBD" if unknown)
   - **Severity**: One of `critical`, `high`, `medium`, `low`

3. **Map type to label**:
   | Type | Label |
   |------|-------|
   | bug | bug |
   | feature | enhancement |
   | docs | documentation |
   | security | security |

4. **Create the issue** using the GitHub MCP server (`mcp__github__issue_write` with method `create`):
   - **owner**: `masa-57`
   - **repo**: `NIC`
   - **title**: The title from arguments
   - **labels**: The mapped label from step 3
   - **body**: Use this template:

```markdown
## Problem
<problem description>

## Proposed Fix
<proposed fix or "TBD — needs investigation">

## Affected Files
<file list or "TBD">

## Severity
<severity level>
```

5. **Report** the created issue number and URL to the user.
