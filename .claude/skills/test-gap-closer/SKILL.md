---
name: test-gap-closer
description: Close audit-driven test gaps with focused, behavior-first tests tied to debt IDs.
---

# Test Gap Closer

## Inputs

- debt IDs (e.g. `C4`, `H-T3`, `M-T10`)
- target module(s)

## Procedure

1. Read debt row details from `docs/audit/debt_register_148.csv`.
2. Identify missing behavior and expected assertions.
3. Add or update tests in the correct layer:
   - unit for pure logic
   - integration for DB/query/ORM behavior
   - e2e for cross-service critical flow
4. Ensure tests fail before fix (when practical), then pass after fix.
5. Run minimal targeted suite, then full relevant suite.
6. Update debt row notes with test file references.

## Standards

- avoid over-mocking DB behavior when query correctness is under test
- include at least one negative/error-path assertion for bug fixes
- keep fixtures deterministic
