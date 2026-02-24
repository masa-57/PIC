---
name: pre-commit
description: Run before committing code. Validates all quality gates pass.
---

# Pre-Commit Verification

Before committing, run ALL of the following. If any fail, fix before committing:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy src/nic/ --ignore-missing-imports
uv run pytest -m unit -x
```

## TODO/FIXME Check

Note: The PostToolUse hook catches TODOs as you write them. This step catches pre-existing orphan TODOs in staged files:

```bash
git diff --cached --name-only -- '*.py' | xargs grep -nE '\bTODO\b|\bFIXME\b' 2>/dev/null | grep -vE '#[0-9]+'
```

If any results appear, either:
- Add an issue reference: `TODO(#42): description`
- Create an issue first with `/create-issue` and reference it

## Commit

Commit message format: `type: description` where type is one of:
feat, fix, refactor, test, docs, chore, ci

Example: `feat: add bulk product creation endpoint`
