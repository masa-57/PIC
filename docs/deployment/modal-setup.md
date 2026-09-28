# Modal Setup Guide

[Modal](https://modal.com) can run PIC's jobs (ingest, clustering, URL ingest, Google Drive sync) as serverless GPU functions instead of the local `pic-worker`.

This is optional. The default is `PIC_WORKER_BACKEND=local`: the Compose `worker` service runs jobs and PIC never contacts Modal. Use Modal when you have no GPU host, or want jobs to scale to zero.

## How it fits together

- The API creates a job row, then spawns the matching Modal function. It needs `PIC_WORKER_BACKEND=modal` and a Modal token.
- Modal functions read their settings from a Modal secret named `pic-env`, not from the API host.
- `pic-worker` refuses to start unless `PIC_WORKER_BACKEND=local`, so a job never runs on both backends. With Modal, do not run the Compose `worker` service (for example, `docker compose up -d db api`).

## Requirements

- A Modal account ([modal.com](https://modal.com)).
- The Modal CLI. It is already a PIC dependency, so `uv run modal ...` works after `uv sync`. Authenticate once with `uv run modal setup`.
- **Object storage that Modal can reach**: any S3-compatible service (AWS S3, Cloudflare R2, MinIO on a public endpoint) or Google Cloud Storage. The local storage backend does not work with Modal, because Modal containers cannot read the API host's disk.
- **A database that Modal can reach** over the internet. The Compose `db` service listens on `127.0.0.1` only, so Modal cannot use it as is. Use a hosted Postgres with pgvector, or expose your own with TLS and a strong password.

## Configure the API host

Set these on the API (in Compose, in the `x-pic-env` block of `docker-compose.yml`, then recreate the `api` container):

| Variable | Value |
|---|---|
| `PIC_WORKER_BACKEND` | `modal` |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | A Modal API token, created in the Modal dashboard. Without it the API cannot spawn functions and job requests fail with 503. |
| `PIC_STORAGE_BACKEND` | `s3` or `gcs`, with the matching `PIC_S3_*` or `PIC_GCS_*` settings |

## Create the `pic-env` secret

Create a Modal secret named `pic-env` with the worker settings. Example for S3-compatible storage (the endpoint shown is Cloudflare R2; leave `PIC_S3_ENDPOINT_URL` empty for AWS S3):

```bash
uv run modal secret create pic-env \
  PIC_DATABASE_URL="postgresql+asyncpg://user:pass@db.example.com:5432/pic" \
  PIC_STORAGE_BACKEND="s3" \
  PIC_S3_ENDPOINT_URL="https://<account-id>.r2.cloudflarestorage.com" \
  PIC_S3_ACCESS_KEY_ID="your-access-key" \
  PIC_S3_SECRET_ACCESS_KEY="your-secret-key" \
  PIC_S3_BUCKET="pic-images"
```

For Google Cloud Storage, set `PIC_STORAGE_BACKEND="gcs"`, `PIC_GCS_BUCKET`, `PIC_GCS_PROJECT_ID` and `PIC_GCS_CREDENTIALS_JSON` instead of the `PIC_S3_*` values.

To use Google Drive sync, also add `PIC_GDRIVE_FOLDER_ID` and `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` (see [gdrive-setup-guide.md](../gdrive-setup-guide.md)).

The database and storage settings must match the API's, so both sides see the same data. The workers do not need `PIC_API_KEY`.

To change the secret later, edit it in the Modal dashboard, or run `modal secret create --force pic-env ...` with the full set of values (it replaces the whole secret).

## Deploy

```bash
uv run modal deploy src/pic/modal_app.py
```

CI deploys the same way and tags each deployment with the commit SHA (`--tag "${GITHUB_SHA}"`).

This deploys the Modal app `pic` with these functions:

| Function | What it does | Hardware |
|---|---|---|
| `run_cluster` | L1 (HDBSCAN on DINOv2 cosine distance) + L2 (UMAP + HDBSCAN) clustering | T4 GPU |
| `run_pipeline` | Discover, dedup, ingest, then cluster | T4 GPU |
| `run_url_ingest` | Download images from URLs, store them, optionally queue a pipeline job | CPU |
| `sync_gdrive_to_r2` | Google Drive sync: download, dedup, embed, upload to storage, cluster | T4 GPU |
| `check_gdrive_for_new_files` | Cron (every 15 minutes) that spawns `sync_gdrive_to_r2` when new files exist | CPU |

## Google Drive cron

`check_gdrive_for_new_files` runs every 15 minutes (`*/15 * * * *` in `modal_app.py`). It does nothing unless both `PIC_GDRIVE_FOLDER_ID` and `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` are in `pic-env`.

This cron exists only on Modal. With the local worker, trigger Google Drive sync yourself (see the Google Drive guide).

Check the app is deployed:

```bash
uv run modal app list  # should show the "pic" app
```

## CI/CD

`.github/workflows/ci-cd.yml` has a `deploy-modal` job. It runs on pushes to `main` only, after lint, unit and integration pass. Add these repository secrets to enable it:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`

If `MODAL_TOKEN_ID` is not set, the job skips the deploy and prints a notice. There is no staging deploy.

## Monitoring

```bash
# Recent logs for the app (add -f to stream)
uv run modal app logs pic

# Deployment history (one entry per deploy, tagged with the commit SHA from CI)
uv run modal app history pic
```

The Modal dashboard shows each function's runs, failures and logs. Job status is also in PIC itself: `GET /api/v1/jobs` and the **Runs** page in the web UI.
