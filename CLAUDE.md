# CLAUDE.md

This file provides guidance specific to Claude Code (claude.ai/code).

**Full project documentation lives in [AGENTS.md](./AGENTS.md)** — read it for architecture,
code structure, setup, and conventions.

## Quick Reference

```bash
uv run pytest -m unit                              # Fast unit tests
uv run ruff check src/ tests/ scripts/             # Lint
uv run ruff format --check src/ tests/ scripts/    # Format check
uv run mypy src/nic/                               # Type check
uv run pip-audit                                   # Security audit
python3 scripts/debt_sync.py validate --strict      # Debt register integrity
python3 scripts/debt_sync.py report --out-dir docs/audit/reports
make backup-db NIC_POSTGRES_URL=...                 # Logical DB backup
make restore-db NIC_POSTGRES_URL=... BACKUP_FILE=backups/nic_*.sql
```

## Quality Gates & Code Standards

Defined in [AGENTS.md](./AGENTS.md#quality-gates). **All 5 quality gates MUST pass before every commit** — use `/quality-check` to run them all.

## Key Gotchas

- DB enums use `StrEnum` — DB values are **UPPERCASE** (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `INGEST`, `CLUSTER_FULL`, `PIPELINE`, `GDRIVE_SYNC`). Use UPPERCASE in raw SQL.
- DB `has_embedding` is integer (0/1), not boolean — use `= 0` not `= false` in raw SQL
- Tests must not hardcode `.env` values — CI/CD has no `.env`, use `settings.*` dynamically
- FastAPI `Depends()`/`Query()` in defaults triggers ruff B008 — this rule is ignored
- `Dockerfile.railway` requires `--no-sync` flag on `uv run` CMD (appuser can't modify root-owned venv)
- Modal functions use lazy imports inside function bodies so secrets load before `settings`
- Pipeline/cluster/gdrive workers use PostgreSQL advisory lock (`0x4E494301`) — concurrent runs fail with 409
- CI integration tests use `pgvector/pgvector:pg16` and create `vector` extension before running Alembic migrations
- Trivy CI image scan is configured for vulnerabilities only (`scanners: vuln`) to avoid secret-scan noise in build artifacts
- CodeQL workflow uses `github/codeql-action@v4`; when repository code scanning is disabled, workflow exits cleanly with a skip message

## Critical Rules

- **NEVER make direct changes to Neon DB** — all schema changes must go through Alembic migrations
- **NEVER deploy to Railway directly** — all deployments go through GitHub Actions CI/CD via push to main
- **NEVER build/push Docker images locally** — push code to GitHub; Railway auto-deploys, Modal deploys via CI/CD

## CI/CD Workflows

- `ci-cd.yml` — Main pipeline: lint, debt-integrity, container-scan, unit-test, integration-test, deploy-modal (on main push)
- `deploy-staging.yml` — Staging deploy on push to `staging` branch (lint + test + deploy)
- `debt-register-audit.yml` — Weekly scheduled debt register audit (Mondays 05:30 UTC, also manual dispatch)
- `codeql.yml` — CodeQL analysis; skips upload gracefully when repo code scanning is disabled

## Claude-Specific Notes

- Pre-commit hooks (`.pre-commit-config.yaml`) run ruff check + format automatically on commit
- Use `/quality-check` before committing to run all quality gates
- Use `.claude.local.md` for personal preferences not shared with the team (gitignored)
- Debt automation script `scripts/debt_sync.py` supports validation, reporting, and issue creation (dry-run/apply)
- Plugin usage policy lives in `docs/automation/plugin-policy.md`

### Available Skills (`.claude/skills/`)

| Skill | Purpose |
|-------|---------|
| `/quality-check` | Run all quality gates before commit |
| `/pre-commit` | Validate all gates pass before committing |
| `/new-endpoint` | Scaffold a new API endpoint with tests |
| `/gen-test <module>` | Generate unit test stubs for a module |
| `/db-migrate` | Generate and apply Alembic migrations safely |
| `/migration-safety` | Safe migration with forward/backward verification |
| `/api-review` | Review endpoints for REST design compliance |
| `/perf-review` | Performance review checklist for changed files |
| `/triage-issues` | Fetch/group/prioritize open GitHub issues |
| `/issue-close-verifier` | Verify a GitHub issue is truly fixed before closure |
| `/release-smoke` | Post-deploy smoke verification |
| `/debt-batch-execute` | Execute a batch of debt rows end-to-end |
| `/test-gap-closer` | Close test gaps tied to debt IDs |

### Custom Hooks (`.claude/hooks/`)

- `block-commands.sh` — Block dangerous commands (direct DB changes, etc.)
- `block-schema-changes.sh` — Prevent direct schema modifications outside Alembic
- `check-todo-refs.sh` — Ensure TODOs reference GitHub issues
- `run-related-tests.sh` — Auto-run tests related to changed files

### Custom Agents (`.claude/agents/`)

`code-review-expert`, `oracle`, `performance-reviewer`, `duplication-detector`, `security-reviewer`, `migration-reviewer`, and `code-quality` (in `code-quality/`).
