# Deployment Rollback Procedures

This document covers rolling back each part of a PIC deployment: the API and local worker, Modal workers, database migrations, and the data itself.

Before any rollback that touches the database, take a backup (see [database-backup-restore.md](database-backup-restore.md)).

## API and local worker rollback

The `api` and `worker` images are built from the same source, so roll them back together.

Check out the last known-good version and rebuild:

```bash
git checkout <good-commit-sha>        # or a release tag
docker compose up --build -d api worker
```

Or revert the bad commit on your branch and rebuild from it:

```bash
git revert <bad-commit-sha>
docker compose up --build -d api worker   # or redeploy on your container host
```

Note: the `api` service runs `alembic upgrade head` on start. It never downgrades. If the bad version added a migration, the older code runs against the newer schema. If that breaks, downgrade the migration first (see below), using the newer code that still contains it.

## Modal workers rollback

Only relevant with `PIC_WORKER_BACKEND=modal`. CI deploys Modal on each push to `main` and tags the deployment with the commit SHA.

Option 1: roll back with the Modal CLI. `modal app history pic` lists deployments; `modal app rollback pic` redeploys the previous one, and `modal app rollback pic <version>` a specific one:

```bash
uv run modal app history pic
uv run modal app rollback pic
```

Option 2: redeploy a known-good commit yourself:

```bash
git checkout <good-commit-sha>
uv sync --frozen
uv run modal deploy src/pic/modal_app.py --tag "<good-commit-sha>"
```

Option 3: revert the offending commit on `main` and let CI redeploy:

```bash
git revert <bad-commit-sha>
git push origin main
```

Roll back the API too if the change touched both.

## Database rollback (Alembic)

To revert the most recent migration:

```bash
uv run alembic downgrade -1
```

To revert to a specific revision:

```bash
uv run alembic downgrade <revision-id>
```

After reverting, check the current state:

```bash
uv run alembic current
uv run alembic history --verbose
```

To check that the latest migration is reversible (downgrade then upgrade):

```bash
uv run python scripts/rollback_check.py
```

### Important notes

- Take a logical backup before running `alembic downgrade` on real data.
- Some migrations cannot be fully reversed (for example, ones that drop columns or rewrite data). Read the downgrade function before running it.
- Alembic needs a sync URL: set `PIC_DATABASE_URL` to the target database. The `postgresql+asyncpg://` form used by the app is converted automatically.
- With Compose, the database listens on `127.0.0.1:5432`, so run Alembic from the host with `PIC_DATABASE_URL=postgresql+asyncpg://pic:pic_local@localhost:5432/pic?sslmode=disable`.
- Stop the worker during a downgrade (`docker compose stop worker`), and do not restart `api` on the old schema with new code: it would upgrade again on start.

## Data rollback

Use this when data is wrong (bad bulk delete, broken clustering run, corrupted rows), not just code.

### Restore a backup (any deployment)

Restore the most recent good `pg_dump` backup, and the matching storage backup if files were affected. The steps are in [database-backup-restore.md](database-backup-restore.md#restore). In short, with Compose:

1. `docker compose stop api worker`
2. Recreate the empty `pic` database and load the backup with `psql`.
3. Restore `./data` (or the bucket) if needed.
4. `docker compose up -d api worker`

Anything written after the backup is lost, including product curation.

A broken clustering run does not need a restore: running clustering again (`POST /api/v1/clusters/run`, or **Runs** in the web UI) rebuilds L1 groups and L2 clusters from the stored embeddings. Products are kept: they link to images, not to clusters.

### Provider point-in-time restore (optional)

Some hosted Postgres providers can restore to a point in time. Example with Neon:

1. In the Neon console, open the PIC project and go to **Branches**.
2. Create a branch from the production branch at a timestamp (UTC) before the incident.
3. Check the data on the new branch, for example by pointing a local API at it.
4. Update `PIC_DATABASE_URL` to the restored branch on the API host, the local worker, and the Modal `pic-env` secret if you use Modal.
5. Restart the API and workers.
6. Once the restored branch is stable, delete the old branch.

Other providers (AWS RDS, Supabase, and so on) have equivalent features; the PIC side is the same: change `PIC_DATABASE_URL` everywhere and restart.

## Incident response

1. Detect the issue (monitoring, user reports, failing smoke tests).
2. Assess severity: is the service down, degraded, or is data at risk?
3. If data is at risk, stop writes immediately (`docker compose stop api worker`, or remove the API key).
4. Take a backup of the current state.
5. Run the matching rollback procedure above.
6. Afterwards, write down the timeline, root cause and follow-up actions.

If you discover a security-impacting incident, see [SECURITY.md](../../SECURITY.md).
