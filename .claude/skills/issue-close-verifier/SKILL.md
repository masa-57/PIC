---
name: issue-close-verifier
description: Verify a GitHub issue is truly fixed before closure (code, tests, docs, and debt register consistency).
---

# Issue Close Verifier

## Procedure

1. Fetch issue details and acceptance criteria.
2. Map criteria to changed files and test evidence.
3. Validate behavior with targeted commands.
4. Ensure regression test exists for bug fixes.
5. Confirm `docs/audit/debt_register_148.csv` row status aligns with issue state.
6. Close issue only when all checks pass; otherwise comment with missing items.

## Required Evidence

- file-level implementation references
- command/test outputs summarized
- explicit acceptance criteria checklist

## Fail Conditions

- partial fix with no test
- docs/debt register not updated
- unresolved edge cases called out in issue body
