# Automation Stack

Last updated: 2026-02-16

This folder contains automation governance and operational docs introduced in Phases 0-3.

## Included

- `agent-rules-source-of-truth.md`: rule hierarchy and drift controls
- `plugin-policy.md`: curated plugin usage policy

## Debt Register Tooling

Use `scripts/debt_sync.py`:

```bash
python3 scripts/debt_sync.py validate --strict --owner masa-57 --repo NIC
python3 scripts/debt_sync.py report --out-dir docs/audit/reports
python3 scripts/debt_sync.py create-issues --limit 20
```

Apply mode for issue creation (writes to GitHub + register):

```bash
python3 scripts/debt_sync.py create-issues --apply --limit 10 --milestone Debt-P2
```

## CI Integrations

- `ci-cd.yml` runs lint + lock checks, debt integrity validation/report artifact upload, Trivy image vulnerability scan, unit tests, integration tests, and main-branch Modal deploy.
- CI integration tests bootstrap `CREATE EXTENSION IF NOT EXISTS vector` before Alembic migrations.
- `debt-register-audit.yml` runs scheduled weekly debt audits.
- `codeql.yml` runs `github/codeql-action@v4` and conditionally skips analysis/upload when repository code scanning is disabled.
- `dependabot.yml` enables automated dependency updates.
