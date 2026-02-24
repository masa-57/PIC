---
name: debt-batch-execute
description: Execute a prioritized batch of debt rows end-to-end (implement, test, register update, and issue linkage).
---

# Debt Batch Execute

Use for planned debt burndown across `docs/audit/debt_register_148.csv`.

## Inputs

- batch size (default: 5)
- filters: severity, domain, milestone

## Procedure

1. Select candidate rows from the register by priority (critical > high > medium > low).
2. Confirm each row has acceptance criteria and target files.
3. Implement fixes in small logical commits.
4. Run quality gates:
   - `uv run ruff check src/ tests/ scripts/`
   - `uv run mypy src/nic/ --ignore-missing-imports`
   - `uv run pytest -m unit -x`
   - targeted integration tests for DB/API changes
5. Update register fields (`status`, `notes`, `github_issue` if created).
6. Summarize completed IDs, tests run, and remaining risks.

## Exit Criteria

- all selected rows moved forward with code/tests and register updates
- no silent TODO/FIXME without issue reference
