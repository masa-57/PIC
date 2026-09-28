# Backup and Restore Runbook

This runbook covers backing up and restoring a PIC deployment.

## What to back up

PIC keeps data in two places. A backup needs both.

| Data | Where it lives |
|---|---|
| Images metadata, embeddings, L1 groups, L2 clusters, jobs, and curated products (titles, descriptions, tags, image links) | PostgreSQL |
| Image files: the inbox (`images/`), `processed/`, `rejected/` and `thumbnails/` | Storage: `./data` on the host with the local backend (the Compose default), or your S3-compatible / GCS bucket |

Curated products exist only in the database. If you lose the database, you lose your curation work, even if the image files survive. If you lose storage, the database points at files that no longer exist.

## Backup policy

1. Take a logical database backup before risky operations: migrations, upgrades, bulk deletes.
2. Take scheduled backups at least weekly (daily if you curate products often).
3. Back up storage on the same schedule.
4. Keep copies somewhere other than the PIC host.
5. If your Postgres provider offers automated backups or point-in-time restore, turn them on. They add to logical backups; they do not replace them.

## Database backup

### Docker Compose (default)

The Compose `db` service uses user `pic` and database `pic`. Dump it from inside the container, so you need no local Postgres tools:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U pic --no-owner --no-privileges pic \
  > "backups/pic_$(date +%Y%m%d_%H%M%S).sql"
```

`-T` stops Compose from allocating a terminal, which would corrupt the output file.

### Any Postgres (Makefile)

`make backup-db` runs `pg_dump` from your machine against any reachable database and writes a timestamped `.sql` file under `backups/`:

```bash
make backup-db PIC_POSTGRES_URL="postgresql://user:pass@host:5432/pic"
```

Notes:

- `PIC_POSTGRES_URL` is a plain libpq URL (`postgresql://...`), not the `postgresql+asyncpg://...` URL the app uses.
- Your local `pg_dump` must be the same major version as the server or newer. The Compose image is Postgres 18.
- The Compose `db` listens on `127.0.0.1:5432`, so from the same host you can use `postgresql://pic:pic_local@localhost:5432/pic`.
- Use a role that can read every table.

## Storage backup

- **Local backend (Compose default)**: copy the `./data` directory, for example `rsync -a data/ /backup/pic-data/` or a `tar` archive. For a consistent copy, stop the worker first (`docker compose stop worker`), so no job is moving files.
- **S3-compatible or GCS**: use your provider's tools. Examples: bucket versioning, replication to a second bucket, or a scheduled `rclone sync` / `aws s3 sync` to another location.

Take the database and storage backups close together in time.

## Restore

Restore into a scratch database first whenever you can, and check it before touching the live one.

The dump includes the `vector` extension and the full schema. Restore it into an **empty** database; restoring over existing tables fails.

### Docker Compose

```bash
# 1. Stop the processes that write to the database
docker compose stop api worker

# 2. Recreate an empty database
docker compose exec db dropdb -U pic --force pic
docker compose exec db createdb -U pic pic

# 3. Load the backup
docker compose exec -T db psql -U pic -d pic -v ON_ERROR_STOP=1 < backups/pic_YYYYMMDD_HHMMSS.sql

# 4. Restore ./data from the matching storage backup, then start again
docker compose up -d api worker
```

The `api` service runs `alembic upgrade head` on start, so a backup from an older PIC version is migrated forward.

### Any Postgres (Makefile)

```bash
make restore-db \
  PIC_POSTGRES_URL="postgresql://user:pass@host:5432/pic" \
  BACKUP_FILE=backups/pic_YYYYMMDD_HHMMSS.sql
```

The target database must be empty and the role needs permission to create the `vector` extension.

### Provider point-in-time restore (optional)

Hosted providers such as Neon, AWS RDS or Supabase can restore to a point in time, usually into a new branch or instance. Follow your provider's docs, then point `PIC_DATABASE_URL` at the restored database and restart the API and workers. Storage is not covered by this; restore it separately if needed.

## Restore verification checklist

1. Bring the schema up to date: `uv run alembic upgrade head` (Compose does this when `api` starts).
2. Check health: `GET /health` returns `"database": "connected"`.
3. Open the web UI at `/ui` and check that clusters and products are there, and that thumbnails load.
4. Spot-check API paths: `/api/v1/images`, `/api/v1/clusters`, `/api/v1/products`.
5. Compare row counts for key tables (`images`, `products`, `l1_groups`, `l2_clusters`, `jobs`) with what you expect:

   ```bash
   docker compose exec db psql -U pic -d pic -c "SELECT count(*) FROM images;"
   ```

## Incident procedure

1. Stop writes if data integrity is at risk (`docker compose stop api worker`, or disable the API key).
2. Back up the current state (database and storage) before restoring anything, even if it looks broken.
3. Restore into a scratch database first and verify.
4. Restore the live deployment only after that check passes.
5. Write down the timeline, root cause and follow-up actions.
