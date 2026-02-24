---
name: migration-safety
description: Safe migration workflow with forward/backward verification and operational checks.
---

# Migration Safety

## Procedure

1. Generate migration:
   - `uv run alembic revision --autogenerate -m "<message>"`
2. Review migration for:
   - reversibility (`upgrade` + `downgrade`)
   - data safety (no unintended drops)
   - pgvector/index integrity
3. Apply migration on test DB:
   - `uv run alembic upgrade head`
4. Run rollback check:
   - `uv run alembic downgrade -1`
   - `uv run alembic upgrade head`
5. Run integration tests touching affected tables.
6. Document operational impact in PR notes.

## Guardrails

- never mutate schema directly via raw SQL in production
- include migration file in code review scope
