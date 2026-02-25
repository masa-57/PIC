# Architecture Overview

PIC (Product Image Clustering) consists of four main components that can be deployed on any infrastructure.

![Architecture Diagram](../images/architecture.svg)

## Components

```
                    ┌─────────────────┐
                    │   API Server    │
                    │   (FastAPI)     │
                    └────┬───────┬────┘
                         │       │
              dispatch   │       │  read/write
              jobs       │       │
                         ▼       ▼
                ┌──────────┐  ┌──────────────────┐
                │   GPU    │  │   PostgreSQL      │
                │ Workers  │  │   + pgvector      │
                └────┬─────┘  └──────────────────┘
                     │
              read/write images
                     │
                     ▼
                ┌──────────────────┐
                │  Object Storage  │
                │  (S3-compatible) │
                └──────────────────┘
```

### API Server (FastAPI)

The REST API handles all client requests: image management, clustering triggers, search, and pipeline orchestration.

- **Runtime**: Python 3.12, async (uvicorn)
- **Resources**: 512MB-1GB RAM, 1 vCPU minimum
- **Network**: Needs access to PostgreSQL, object storage, and worker dispatch
- **Stateless**: Can be scaled horizontally

### GPU Workers

ML workloads run as separate processes: DINOv2 embedding generation, HDBSCAN clustering, and Google Drive sync.

- **Runtime**: Python 3.12 with PyTorch, torchvision, HDBSCAN
- **Resources**: GPU recommended (CUDA), 8GB+ RAM (16GB for 10k+ images)
- **Current implementation**: Modal serverless functions (see [modal-setup.md](modal-setup.md))
- **Alternative**: Can run as local processes (see [self-hosted.md](self-hosted.md))

### PostgreSQL + pgvector

Stores image metadata, cluster assignments, job state, and 768-dimensional DINOv2 embeddings with HNSW index for fast similarity search.

- **Version**: PostgreSQL 16+ with pgvector extension
- **Resources**: 1GB+ RAM (scales with dataset size)
- **Key indexes**: HNSW on embedding column, composite indexes on frequently queried columns

### Object Storage (S3-compatible)

Stores image files. Any S3-compatible service works (tested with Cloudflare R2).

- **Buckets**: One bucket with `images/`, `processed/`, and `rejected/` prefixes
- **Lifecycle**: Images move from `images/` to `processed/` after ingestion, or `rejected/` if duplicate

## Reference Deployments

### Local Development

```bash
docker compose up db -d          # PostgreSQL with pgvector
uv run fastapi dev src/pic/main.py  # API server
# Workers called directly via Modal CLI or local import
```

### Cloud (Railway + Modal)

| Component | Platform | Notes |
|-----------|----------|-------|
| API Server | Railway | Auto-deploys from GitHub |
| GPU Workers | Modal | Serverless, pay-per-use GPU |
| Database | Neon / Railway PostgreSQL | Managed PostgreSQL with pgvector |
| Object Storage | Cloudflare R2 | S3-compatible, free egress |

### Self-Hosted

Any combination of:
- API: Docker container or direct `uvicorn` process
- Workers: GPU server with PyTorch + cron/supervisor
- Database: Any PostgreSQL 16+ with pgvector
- Storage: MinIO, AWS S3, GCS (via S3 compatibility), or any S3-compatible service

## Environment Variables

All configuration is via environment variables with the `PIC_` prefix.

| Variable | Required | Description |
|----------|----------|-------------|
| `PIC_DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg) |
| `PIC_API_KEY` | Production | API authentication key |
| `PIC_S3_ENDPOINT_URL` | Yes | S3-compatible endpoint |
| `PIC_S3_ACCESS_KEY_ID` | Yes | S3 access key |
| `PIC_S3_SECRET_ACCESS_KEY` | Yes | S3 secret key |
| `PIC_S3_BUCKET` | Yes | Bucket name (default: `pic-images`) |
| `PIC_S3_REGION` | No | Region (default: `auto` for R2) |
| `PIC_CORS_ORIGINS` | No | Allowed CORS origins (comma-separated) |
| `PIC_LOG_LEVEL` | No | Log level (default: `INFO`) |
| `PIC_LOG_FORMAT` | No | `json` for structured logging |
| `PIC_MODAL_ENVIRONMENT` | No | Modal environment name |
| `PIC_GDRIVE_FOLDER_ID` | No | Google Drive folder for sync |
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` | No | GDrive service account credentials |

See `.env.example` for a complete reference.
