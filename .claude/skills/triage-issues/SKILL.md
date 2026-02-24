---
name: triage-issues
description: Fetch open GitHub issues, group by label/severity, suggest priority order, and identify quick wins.
---

# Triage Open Issues

Fetch and analyze all open GitHub issues in `masa-57/NIC` to help plan what to work on next.

## Procedure

1. **Fetch open issues** using the GitHub MCP server (`mcp__github__list_issues`):
   - **owner**: `masa-57`
   - **repo**: `NIC`
   - **state**: `open`
   - **perPage**: 30

2. **For each issue**, extract:
   - Issue number and title
   - Labels
   - Severity (from body if present, otherwise infer from labels: `bug` → high, `security` → critical, `enhancement` → medium, `documentation` → low)
   - Created date and age

3. **Group issues** by label into sections:
   - Security (critical)
   - Bugs (high)
   - Enhancements (medium)
   - Documentation (low)
   - Unlabeled (needs triage)

4. **Within each group**, sort by:
   - Severity (from issue body if available)
   - Age (older issues first)

5. **Identify quick wins** — issues that are likely small scope:
   - Title contains words like "typo", "rename", "update", "add comment", "fix test"
   - Body mentions only 1-2 files
   - Labels include `documentation`

6. **Present the triage report** in this format:

```
## Issue Triage Report

### Critical / Security
- #N — Title (age: X days)

### High / Bugs
- #N — Title (age: X days)

### Medium / Enhancements
- #N — Title (age: X days)

### Low / Documentation
- #N — Title (age: X days)

### Needs Triage (unlabeled)
- #N — Title (age: X days)

### Quick Wins
- #N — Title (reason: small scope)

### Recommended Next Action
<suggestion based on priority and quick wins>
```
