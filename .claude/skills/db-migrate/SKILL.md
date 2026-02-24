---
name: db-migrate
description: Generate and apply Alembic database migrations safely.
---

# Database Migration Workflow

When generating or applying Alembic migrations, follow these steps in order.

## Step 1: Check Current State
```bash
uv run alembic current
uv run alembic history --verbose -r -3:head
```
Confirm which revision the database is at before making changes.

## Step 2: Generate Migration (if creating a new one)
```bash
uv run alembic revision --autogenerate -m "<description>"
```
Use a short, descriptive message (e.g., "add tags column to products", "create jobs table").

## Step 3: Review the Generated Migration

Read the new migration file in `src/nic/migrations/versions/`. Check for:
- **Correct upgrade/downgrade**: Both paths must be present and reversible
- **pgvector columns**: Ensure `Vector(768)` type is preserved, not converted to generic
- **HNSW indexes**: Don't accidentally drop the embedding HNSW index
- **Nullable defaults**: New columns should be nullable OR have a server_default to avoid breaking existing rows
- **No data loss**: `op.drop_column()` or `op.drop_table()` should be intentional

## Step 4: Apply Migration
```bash
uv run alembic upgrade head
```

## Step 5: Verify
```bash
uv run alembic current
```
Confirm the database is now at the new head revision.

## Gotchas
- The Alembic env.py uses `sync_database_url` from config (not the async URL)
- Migration files are excluded from ruff linting (`extend-exclude` in pyproject.toml)
- pgvector extension must already be installed on the target database
- Always test migrations locally before applying to production (Neon)
