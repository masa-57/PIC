# NIC — Hierarchical Image Clustering API

Two-level image clustering for ~10k cake images:

- **Level 1**: Groups images of the exact same product (different angles/zoom) using perceptual hashing
- **Level 2**: Groups similar designs (e.g. all "superman" cakes together) using DINOv2 embeddings + HDBSCAN

## Quick Start

```bash
# Prerequisites: Python 3.12, uv, Docker
uv sync
docker compose up db -d
uv run fastapi dev src/nic/main.py
```

API docs at http://localhost:8000/docs

## Upload Images

Upload images to the S3 bucket (under the `images/` prefix). The S3 event trigger will automatically:
1. Create a database record
2. Submit an AWS Batch job to compute pHash + DINOv2 embedding

For bulk upload from a local directory:
```bash
python scripts/seed.py /path/to/cake/images/
```

## Run Clustering

```bash
curl -X POST http://localhost:8000/api/v1/clusters/run
```

This submits a Batch job that runs the full L1 + L2 pipeline.

## Search

```bash
# Find semantically similar images
curl -X POST http://localhost:8000/api/v1/search/similar \
  -H 'Content-Type: application/json' \
  -d '{"image_id": "...", "n_results": 20}'

# Find near-duplicates
curl -X POST http://localhost:8000/api/v1/search/duplicates \
  -H 'Content-Type: application/json' \
  -d '{"image_id": "..."}'
```

## AWS Deployment

Infrastructure managed with AWS CDK:

```bash
cd infra
pip install -r requirements.txt
cdk deploy --all
```

See the [plan](/.claude/plans/) for full architecture details.

## Testing

```bash
uv run pytest -m unit          # Fast, no external deps
uv run pytest -m integration   # Requires Docker
uv run pytest -m e2e           # Full pipeline
```

## Database Operations

```bash
# Create logical backup (requires NIC_POSTGRES_URL)
make backup-db NIC_POSTGRES_URL="$NIC_POSTGRES_URL"

# Restore from logical backup
make restore-db NIC_POSTGRES_URL="$NIC_POSTGRES_URL" BACKUP_FILE=backups/<file>.sql
```

Detailed runbook: `docs/operations/database-backup-restore.md`

## Type Checking

Type checking is run in strict mode (`mypy`) locally and in CI:

```bash
uv run mypy src/nic/
```

Some third-party libraries in this project do not ship type stubs. These are handled via
`ignore_missing_imports = true` in `pyproject.toml` so local and CI results stay consistent.
