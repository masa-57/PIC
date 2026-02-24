# Database Backup and Restore Runbook

This runbook defines the minimum backup and restore process for the NIC PostgreSQL database.

## Scope

- Primary database: Neon PostgreSQL configured via `NIC_POSTGRES_URL`.
- Goal: ensure recoverability from operator error, bad deploy, and data corruption.

## Backup Policy

1. Platform backups:
- Verify Neon automated backups / point-in-time restore settings are enabled in the Neon console.
- Record retention window and restore point objective in team ops notes.

2. Logical backups:
- Run a logical backup before risky schema/data operations.
- Run scheduled logical backups at least weekly.

## Prerequisites

1. `pg_dump` and `psql` are installed locally.
2. `NIC_POSTGRES_URL` is set to the target database.
3. Use a credential with read access for backup and write access for restore.

## Create Backup

```bash
make backup-db NIC_POSTGRES_URL="$NIC_POSTGRES_URL"
```

The command writes a timestamped `.sql` file under `backups/`.

## Restore Backup

Important: restore to a staging/temporary database first whenever possible.

```bash
make restore-db \
  NIC_POSTGRES_URL="$NIC_POSTGRES_URL" \
  BACKUP_FILE=backups/nic_YYYYMMDD_HHMMSS.sql
```

## Restore Verification Checklist

1. Run migrations status check:
- `uv run alembic upgrade head`

2. Run smoke checks:
- `uv run pytest -m unit -q`
- `uv run pytest -m integration -q` (if environment is available)

3. Validate critical API paths:
- `/health`
- `/api/v1/images`
- `/api/v1/clusters`

4. Confirm expected row counts for key tables (`images`, `jobs`, `l1_groups`, `l2_clusters`).

## Incident Procedure

1. Freeze write traffic if data integrity is at risk.
2. Capture current state backup (`make backup-db`) before restore attempt.
3. Restore to staging first and validate.
4. Restore production only after staging verification succeeds.
5. Document timeline, root cause, and follow-up actions in postmortem notes.
