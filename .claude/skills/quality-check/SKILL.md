---
name: quality-check
description: Run full project quality checks. Use when finishing a feature, before committing, or when asked to verify code quality.
---

# Quality Check Procedure

Run these checks in order. Stop and fix issues before proceeding to the next step.

## Step 1: Lint
```bash
uv run ruff check src/ tests/ scripts/
```
Fix all errors before continuing.

## Step 2: Format
```bash
uv run ruff format src/ tests/ scripts/
```

## Step 3: Type Check
```bash
uv run mypy src/nic/ --ignore-missing-imports
```
Fix all type errors.

## Step 4: Unit Tests
```bash
uv run pytest -m unit --tb=short
```
All tests must pass.

## Step 5: Security Audit
```bash
uv run pip-audit
```

## Step 6: Coverage Check
```bash
uv run pytest -m unit --cov=src/nic --cov-report=term --cov-fail-under=70
```

Report results summary to the user.
