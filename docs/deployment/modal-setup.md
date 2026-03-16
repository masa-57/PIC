# Modal Setup Guide

[Modal](https://modal.com) runs PIC's GPU workloads (embedding generation, clustering, Google Drive sync) as serverless functions.

## Prerequisites

- Modal account ([modal.com](https://modal.com))
- Modal CLI installed: `pip install modal`
- Modal authentication configured: `modal setup`

## Configure Secrets

Create a Modal secret named `pic-env` containing all required environment variables:

```bash
modal secret create pic-env \
  PIC_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/pic" \
  PIC_S3_ENDPOINT_URL="https://your-r2-endpoint.r2.cloudflarestorage.com" \
  PIC_S3_ACCESS_KEY_ID="your-access-key" \
  PIC_S3_SECRET_ACCESS_KEY="your-secret-key" \
  PIC_S3_BUCKET="pic-images" \
  PIC_GDRIVE_FOLDER_ID="your-folder-id" \
  PIC_GDRIVE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

## Deploy

```bash
# Deploy all Modal functions
modal deploy src/pic/modal_app.py

# Deploy with a specific tag (used in CI/CD)
modal deploy src/pic/modal_app.py --tag "v0.2.0"
```

This deploys:
- `run_ingest` -- Processes uploaded images (hash + DINOv2 embedding, then moves objects to `processed/`)
- `run_cluster` -- Runs hierarchical clustering (L1 HDBSCAN on cosine distance + L2 UMAP/HDBSCAN on DINOv2 embeddings)
- `run_pipeline` -- End-to-end pipeline (discover, dedup, ingest, cluster)
- `run_url_ingest` -- Downloads images from URLs, stores them, and can queue a separate pipeline job
- `sync_gdrive_to_r2` -- Syncs images from Google Drive
- `check_gdrive_for_new_files` -- Cron checker that spawns GDrive sync work when needed

## Cron Jobs

The Modal app includes a scheduled function for Google Drive sync. After deploying, verify it's registered:

```bash
modal app list  # Should show "pic" app
```

The GDrive sync cron runs on a schedule defined in `modal_app.py`. It only triggers when both `PIC_GDRIVE_FOLDER_ID` and `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` are configured.

## CI/CD Integration

The GitHub Actions workflow automatically deploys to Modal on push to `main`. Required secrets in your GitHub repository:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`

For staging:
- `STAGING_MODAL_TOKEN_ID`
- `STAGING_MODAL_TOKEN_SECRET`

## Monitoring

```bash
# View recent function runs
modal app logs pic

# Check function status
modal function list --app pic
```
