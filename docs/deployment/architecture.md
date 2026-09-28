# Architecture Overview

PIC (Product Image Clustering) is one FastAPI app, one worker, PostgreSQL with
pgvector, and object storage. All of it runs on one machine with Docker
Compose, or on any infrastructure you choose.

![Architecture Diagram](../images/architecture.svg)

## Components

```
  Image sources: browser folder upload · image URLs · Google Drive · files in the inbox
                                   │
                                   ▼
        ┌──────────────────────────────────────┐        ┌─────────────────────┐
        │ FastAPI app                          │ jobs,  │ PostgreSQL          │
        │  JSON API /api/v1 · web UI /ui       │ reads  │  + pgvector         │
        │  (never runs ML itself)              ├───────►│ images, embeddings, │
        └───────────────┬──────────────────────┘        │ groups, clusters,   │
                        │ uploads to inbox               │ products, jobs      │
                        ▼                                └──────────▲──────────┘
        ┌──────────────────────────┐   read / move    ┌─────────────┴──────────┐
        │ Object storage           │◄─────────────────┤ Worker                 │
        │ local · S3 · R2 · MinIO  │                  │ pic-worker (default)   │
        │ · GCS                    │                  │ or Modal               │
        └──────────────────────────┘                  └────────────────────────┘
```

### FastAPI app

Serves the JSON API under `/api/v1` and the server-rendered web UI under `/ui`
(Jinja2 templates plus vendored htmx, no build step). It records jobs in
Postgres and hands them to the worker backend. It never computes embeddings or
clusters. With the local storage backend it also serves stored files at `/files`.

- **Runtime**: Python 3.12, async (uvicorn via `fastapi run`)
- **Resources**: 512MB-1GB RAM, 1 vCPU minimum
- **Auth**: `PIC_API_KEY` protects both the API (`X-API-Key` header) and the UI
  (login page, 30-day session cookie)
- **Scaling**: several instances can run behind a load balancer only with shared
  storage (S3/GCS). With the local backend, uploads land on the instance's disk.

### Workers

ML work runs outside the API: DINOv2 embeddings, HDBSCAN and UMAP clustering,
URL ingest and Google Drive sync. `PIC_WORKER_BACKEND` picks where:

| Backend | How jobs reach it | Guide |
|---|---|---|
| `local` (default) | The API leaves the job PENDING in Postgres; `pic-worker` claims it with `FOR UPDATE SKIP LOCKED` and runs it | [self-hosted.md](self-hosted.md) |
| `modal` | The API spawns the matching Modal function (needs S3/GCS storage) | [modal-setup.md](modal-setup.md) |

Both backends call the same job code in `src/pic/worker/`. Job input is stored
on the job row (`jobs.params`). Only one pipeline, clustering or Drive sync job
runs at a time (PostgreSQL advisory lock).

- **Runtime**: Python 3.12 with PyTorch, torchvision, scikit-learn, umap-learn
- **Resources**: 8GB+ RAM (16GB for 10k+ images). A GPU speeds up embeddings:
  T4 on Modal, Apple MPS when `pic-worker` runs natively on macOS. The Linux
  Docker image is CPU-only.

### PostgreSQL + pgvector

Stores images and their 768-dimensional DINOv2 embeddings (HNSW index for
similarity search), L1 groups, L2 clusters, products and jobs.

- **Version**: PostgreSQL 16+ with pgvector (Compose and CI use `pgvector/pgvector:pg18`). The initial migration creates the `vector` extension.
- **Migrations**: `uv run alembic upgrade head`. Compose runs it when the API starts; the plain `api` image does not.
- **Resources**: 1GB+ RAM (scales with dataset size)
- **Clustering vs. products**: each clustering run deletes and rebuilds L1 groups and L2 clusters. Products are never changed by clustering.

### Object storage (pluggable backend)

| Backend | Config value | Use case |
|---------|-------------|----------|
| **Local** | `PIC_STORAGE_BACKEND=local` | Docker Compose default and single-machine installs; files served at `/files` without auth |
| **S3-compatible** | `PIC_STORAGE_BACKEND=s3` (the code default when unset) | AWS S3, Cloudflare R2, MinIO; recommended for public deployments |
| **GCS** | `PIC_STORAGE_BACKEND=gcs` | Google Cloud deployments |

- **Prefixes**: `images/` (inbox), `processed/`, `rejected/`, `thumbnails/`
- **Lifecycle**: images move from `images/` to `processed/` after ingestion, or to `rejected/` if they are exact duplicates
- **Production guard**: `PIC_ENV=production` refuses to start with the local backend

## Reference deployments

### Single machine (default)

```bash
mkdir -p data/images
docker compose up --build -d     # db + api (migrates on start) + pic-worker
```

On macOS, run `docker compose up -d db api` and start `pic-worker` natively to
use the Apple GPU. See [self-hosted.md](self-hosted.md).

### Server

| Component | Options |
|-----------|---------|
| API | Any container host, using the `Dockerfile` default (`api`) target, behind a TLS reverse proxy |
| Workers | One `pic-worker` (the `worker` target, or `uv run pic-worker`), or Modal with `PIC_WORKER_BACKEND=modal` |
| Database | Any PostgreSQL 16+ with pgvector: self-hosted, Neon, Supabase |
| Storage | S3-compatible (AWS S3, R2, MinIO) or GCS with private buckets |

## Environment variables

All configuration is via environment variables with the `PIC_` prefix
(`src/pic/config.py`). With Docker Compose they are set in the `x-pic-env`
block of `docker-compose.yml`; for native runs, copy `.env.example` to `.env`.

| Variable | Required | Description |
|----------|----------|-------------|
| `PIC_DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql+asyncpg://…`) |
| `PIC_ENV` | No | `development` (default), `staging`, `production`, `test`; production rejects local storage |
| `PIC_API_KEY` | For any shared deployment | Protects the API and the web UI |
| `PIC_AUTH_DISABLED` | No | Explicit opt-out for unauthenticated mode |
| `PIC_STORAGE_BACKEND` | No | `local`, `s3` (default when unset), `gcs` |
| `PIC_WORKER_BACKEND` | No | `local` (default, `pic-worker`) or `modal` |
| `PIC_S3_ENDPOINT_URL` | S3 only | S3-compatible endpoint (empty for AWS S3) |
| `PIC_S3_ACCESS_KEY_ID` | S3 only | S3 access key |
| `PIC_S3_SECRET_ACCESS_KEY` | S3 only | S3 secret key |
| `PIC_S3_BUCKET` | S3 only | Bucket name (default: `pic-images`) |
| `PIC_GCS_BUCKET` | GCS only | GCS bucket name |
| `PIC_GCS_PROJECT_ID` | GCS only | GCS project ID |
| `PIC_GCS_CREDENTIALS_JSON` | GCS only | Service account JSON |
| `PIC_LOCAL_STORAGE_PATH` | Local only | Filesystem path (default: `data/storage`; Compose uses `/data`) |
| `PIC_LOCAL_STORAGE_BASE_URL` | Local only | Base URL for file links returned by the API |
| `PIC_MAX_UPLOAD_SIZE_MB` | No | Largest request and uploaded file (default: 20) |
| `PIC_DB_SSL_CA` | No | CA bundle for verifying the database's TLS certificate |
| `PIC_LOG_LEVEL` | No | API log level (default: `INFO`) |
| `PIC_GDRIVE_FOLDER_ID` | No | Google Drive folder for sync (API and worker) |
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` | No | Google Drive service account credentials (API and worker) |
| `PIC_GDRIVE_SCOPES` | No | OAuth scopes for Google Drive sync |

See `.env.example` for a commented reference.
