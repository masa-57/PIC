# PIC - Product Image Clustering

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Hierarchical image clustering API for product catalog images. Two-level clustering automatically organizes thousands of product images into meaningful groups:

- **Level 1**: Groups images of the exact same product (different angles, zoom levels) using HDBSCAN on DINOv2 cosine distance
- **Level 2**: Groups visually similar products (shared design, style, or category) using DINOv2 embeddings + HDBSCAN

## Features

- Two-level hierarchical clustering (near-duplicate detection + semantic similarity)
- DINOv2 vision transformer embeddings for high-quality visual similarity
- pgvector-powered vector search for finding similar images
- Full pipeline API for batch ingestion, deduplication, and clustering
- Product management with AI-ready candidate extraction
- Google Drive sync for automated image ingestion
- S3-compatible storage (Cloudflare R2, MinIO, AWS S3)
- API key authentication with timing-safe comparison
- Structured JSON logging with request ID tracking
- Prometheus metrics and Sentry error tracking

## Quick Start

```bash
# Prerequisites: Python 3.12, uv, Docker

# Clone the repository
git clone https://github.com/masa-57/PIC.git
cd PIC

# Install dependencies
uv sync

# Start PostgreSQL with pgvector
docker compose up db -d

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your settings (database, S3, API key)

# Run database migrations
uv run alembic upgrade head

# Start the API server
uv run fastapi dev src/pic/main.py
```

API docs available at http://localhost:8000/docs

## Architecture

PIC uses a two-level clustering approach:

1. **Level 1 (L1)** -- HDBSCAN on DINOv2 cosine distance groups identical products photographed from different angles. Density-based clustering runs on CPU (embeddings computed on GPU).
2. **Level 2 (L2)** -- DINOv2 embeddings + UMAP dimensionality reduction + HDBSCAN clustering groups visually similar products. Runs on GPU for embedding computation.

**Components**:

| Component | Purpose |
|-----------|---------|
| **FastAPI** | REST API for images, clusters, search, products, pipeline |
| **Modal** | Serverless GPU workers for embedding computation and clustering |
| **PostgreSQL + pgvector** | Metadata storage + vector similarity search (HNSW index) |
| **S3-compatible storage** | Image storage with inbox/processed/rejected lifecycle |

**Flows**:

- **Ingestion**: Upload images to S3 `images/` prefix -> compute pHash + DINOv2 embedding -> store vectors in PostgreSQL -> move to `processed/`
- **Clustering**: Triggered via API or pipeline. L1 runs HDBSCAN on DINOv2 cosine distance; L2 runs UMAP + HDBSCAN on DINOv2 embeddings.
- **Pipeline**: Single endpoint for n8n/automation -- discovers, deduplicates, ingests, and clusters in one call.
- **Google Drive sync**: Watches a Drive folder, downloads new images, processes them, and syncs to S3.

## API Overview

All endpoints are under `/api/v1/` and require an API key via `X-API-Key` header (disabled in dev mode).

| Endpoint Group | Description |
|----------------|-------------|
| `/images` | Upload, list, get, delete images |
| `/clusters` | Trigger clustering, list L1 groups and L2 clusters |
| `/search` | Find similar images (vector search) and near-duplicates (pHash) |
| `/products` | CRUD for products created from L1 groups, candidate listing |
| `/pipeline` | Batch pipeline: discover + dedup + ingest + cluster |
| `/gdrive` | Trigger Google Drive sync |
| `/jobs` | List and inspect background job status |
| `/health` | Basic and detailed health checks |

## Deployment

PIC is designed for deployment with:

- **API server**: Any container platform (Railway, Fly.io, Cloud Run, etc.) using `Dockerfile.railway`
- **GPU workers**: Modal serverless functions (`modal deploy src/pic/modal_app.py`)
- **Database**: PostgreSQL with pgvector extension (Neon, Supabase, self-hosted)
- **Object storage**: Any S3-compatible service (Cloudflare R2, MinIO, AWS S3)

See `docs/deployment/` for detailed deployment guides.

## Configuration

Copy `.env.example` to `.env` and configure. Key environment variables:

| Variable | Description |
|----------|-------------|
| `PIC_DATABASE_URL` | PostgreSQL connection string (asyncpg format) |
| `PIC_S3_BUCKET` | S3 bucket name for image storage |
| `PIC_S3_ENDPOINT_URL` | S3-compatible endpoint URL |
| `PIC_S3_ACCESS_KEY_ID` | S3 access key |
| `PIC_S3_SECRET_ACCESS_KEY` | S3 secret key |
| `PIC_API_KEY` | API authentication key (empty = auth disabled) |
| `PIC_SENTRY_DSN` | Sentry DSN for error tracking (optional) |
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` | Google Drive service account JSON (optional) |
| `PIC_GDRIVE_FOLDER_ID` | Google Drive folder ID to watch (optional) |

See `.env.example` for the full list including clustering parameters, embedding settings, and CORS configuration.

## Development

```bash
# Lint
uv run ruff check src/ tests/ scripts/

# Format
uv run ruff format src/ tests/ scripts/

# Type check
uv run mypy src/pic/

# Run unit tests
uv run pytest -m unit

# Run integration tests (requires Docker)
uv run pytest -m integration

# Run all tests
uv run pytest

# Security audit
uv run pip-audit

# Database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
```

A `Makefile` provides shortcuts: `make dev`, `make test`, `make lint`, `make format`, `make migrate`, and more.

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
