# PIC -- Hierarchical Image Clustering API

> **Note for human contributors:** This file provides structured context for AI
> coding assistants (Claude Code, Cursor, GitHub Copilot Workspace, etc.). You
> can safely ignore it -- everything here is also covered in
> [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the docs.

This file provides context and instructions for AI coding agents working with this repository.

## Project Overview

PIC is a hierarchical image clustering API for product catalog images. Two-level clustering:
- **Level 1**: Near-duplicate detection (same product, different angles) via perceptual hashing
- **Level 2**: Semantic similarity (visually similar products) via DINOv2 embeddings + UMAP + HDBSCAN

## Commands

```bash
# Install dependencies (API only)
uv sync
# Install with ML deps (needed for workers/tests with embeddings)
uv sync --extra ml

# Run API locally (requires PostgreSQL with pgvector)
docker compose up db -d
uv run fastapi dev src/pic/main.py

# Run tests
uv run pytest -m unit          # Fast, no external deps
uv run pytest -m integration   # Requires Docker (testcontainers)
uv run pytest -m e2e           # Full pipeline, slow
uv run pytest                  # All tests

# Lint
uv run ruff check src/ tests/ scripts/
uv run ruff format src/ tests/ scripts/

# Type check
uv run mypy src/pic/

# Security audit
uv run pip-audit

# Coverage (70% minimum threshold)
uv run pytest -m unit --cov=src/pic --cov-report=term

# Deploy Modal functions
modal deploy src/pic/modal_app.py

# Database migrations (Alembic)
uv run alembic upgrade head                    # Apply all pending migrations
uv run alembic revision --autogenerate -m "description"  # Generate migration from model changes

# Bulk upload images to R2 (waits for ingestion, then auto-clusters)
python scripts/seed.py /path/to/images/
python scripts/seed.py /path/to/images/ --no-cluster  # Upload only, skip clustering
```

A `Makefile` provides shortcuts: `make dev`, `make test`, `make test-all`, `make lint`, `make format`, `make migrate`, `make seed DIR=/path`, `make audit`.

## Architecture

**Deployment**: Container host (API) + Modal serverless GPU (ML workers) + S3-compatible storage (images) + PostgreSQL/pgvector (metadata + vectors)

**Ingestion flow**: Images uploaded to S3 `images/` via `seed.py` -> Modal `run_ingest` function -> compute pHash + DINOv2 embedding -> store in PostgreSQL -> move to `processed/`

**Clustering flow**: Separate from ingestion. Triggered via `POST /api/v1/clusters/run` or automatically by `seed.py` after upload. Runs UMAP + HDBSCAN on all images with embeddings. Ingestion does NOT auto-cluster.

**Pipeline flow** (n8n integration): `POST /api/v1/pipeline/run` -- single endpoint that discovers images in S3 `images/`, deduplicates via SHA256 content hash, ingests (pHash + DINOv2), then clusters. Duplicates moved to `rejected/`. Uses PostgreSQL advisory lock to prevent concurrent runs.

**Product flow** (post-clustering): After clustering, L1 groups become product candidates. `GET /api/v1/products/candidates` lists unprocessed L1 groups. AI (via n8n) generates title/description/tags, then `POST /api/v1/products` creates a product from an L1 group, linking all member images. Full CRUD on `/api/v1/products`.

**Auth**: API key via `X-API-Key` header on all `/api/v1/*` routes. Set `PIC_API_KEY` env var; if empty/unset, auth is disabled (dev mode). Uses timing-safe comparison.

**Health checks**: `GET /health` (basic) and `GET /health/detailed` (DB connectivity + recent job failures).

**Rate limiting**: Configured via `PIC_RATE_LIMIT_DEFAULT` and `PIC_RATE_LIMIT_BURST` env vars (slowapi).

**R2 lifecycle**: `images/` is an inbox; after successful ingest, objects move to `processed/`. Duplicates (detected by pipeline) move to `rejected/`.

**Google Drive sync flow**: `POST /api/v1/gdrive/sync` or automatic via Modal cron (every 15 min). Tier 1 (CPU cron) checks GDrive for new images -> if found, spawns Tier 2 (GPU worker) that downloads images, computes hashes + embeddings, uploads to S3, moves processed files to GDrive `processed/` subfolder, then runs clustering. Uses same advisory lock as pipeline.

**Key tech choices**: DINOv2 (visual similarity without text bias), pgvector (single DB for metadata + vectors), UMAP + HDBSCAN (60% quality gain over raw high-dim clustering), pHash for L1 (deterministic, fast), Modal (serverless GPU).

## Code Structure

- `src/pic/main.py` -- FastAPI application entry point
- `src/pic/api/` -- FastAPI endpoints (images, clusters, search, jobs, products, gdrive)
- `src/pic/api/pipeline.py` -- Pipeline endpoint for n8n (batch ingest + dedup + cluster)
- `src/pic/api/products.py` -- Product CRUD + candidate listing for AI tagging workflow
- `src/pic/api/deps.py` -- Shared FastAPI dependencies (get_db session)
- `src/pic/api/router.py` -- Central router combining all endpoint routers
- `src/pic/api/gdrive.py` -- Google Drive sync trigger endpoint
- `src/pic/services/` -- Business logic (embedding, clustering, vector_store, image_store, modal_dispatch, gdrive)
- `src/pic/services/clustering_pipeline.py` -- Shared clustering logic used by both cluster and pipeline workers
- `src/pic/services/gdrive.py` -- Google Drive API wrapper (list, download, move files)
- `src/pic/models/` -- SQLAlchemy models (`db.py`) and Pydantic schemas (`schemas.py`)
- `src/pic/worker/` -- Modal job entry points (ingest, cluster, gdrive_sync)
- `src/pic/worker/pipeline.py` -- Pipeline worker (discover, dedup, ingest, cluster)
- `src/pic/worker/gdrive_sync.py` -- Google Drive -> S3 sync worker (download, dedup, embed, cluster)
- `src/pic/worker/entrypoint.py` -- Shared worker entry point logic
- `src/pic/worker/helpers.py` -- Advisory lock, job status helpers (`acquire_advisory_lock`, `mark_job_running/failed/completed`)
- `src/pic/modal_app.py` -- Modal app definition (GPU functions for ingest, clustering, gdrive sync + CPU cron for gdrive check)
- `src/pic/config.py` -- Pydantic Settings (all `PIC_*` env vars)
- `src/pic/core/` -- Database engine, structured JSON logging, API key auth
- `src/pic/migrations/` -- Alembic migrations (uses `sync_database_url` from config)
- `scripts/seed.py` -- Bulk image upload + optional auto-clustering
- `scripts/visualize.py` -- Generates HTML visualization of cluster results
- `docs/n8n-setup-guide.md` -- n8n integration setup documentation
- `docs/n8n-workflows/` -- n8n workflow JSON exports (batch Google Drive upload)
- `TECHNICAL_DEBT.md` -- Tracked technical debt items

## Setup

Copy `.env.example` to `.env` and fill in values. Key vars: `PIC_DATABASE_URL`, `PIC_S3_BUCKET`, `PIC_S3_ENDPOINT_URL`, `PIC_S3_ACCESS_KEY_ID`, `PIC_S3_SECRET_ACCESS_KEY`.

Optional observability: `PIC_SENTRY_DSN` (error tracking, empty = disabled). Prometheus metrics are exposed automatically via `prometheus-fastapi-instrumentator`.

Optional Google Drive sync: `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` (service account JSON string), `PIC_GDRIVE_FOLDER_ID` (folder to watch). Both must be set to enable GDrive sync.

For Modal: run `modal setup` to authenticate, then `modal deploy src/pic/modal_app.py`.

## Conventions

- Async everywhere (asyncpg, SQLAlchemy async sessions)
- Pydantic Settings for config (env prefix `PIC_`, loaded from `.env`)
- Ruff for linting (B008 ignored -- FastAPI Depends pattern)
- mypy for type checking (`strict = true`, `pydantic.mypy` plugin)
- pytest markers: `unit`, `integration`, `e2e`
- Integration tests use testcontainers (PostgreSQL + pgvector) with `NullPool` to avoid asyncpg event-loop binding errors
- Key integration fixtures: `db` (async session), `client` (httpx AsyncClient), `seed_images`, `seed_l1_group`, `seed_l2_cluster`, `seed_job`
- pgvector `Vector(768)` column type for DINOv2 embeddings
- L1/L2 naming: L1 = near-duplicate groups, L2 = semantic clusters
- Pre-commit hooks configured (`.pre-commit-config.yaml`): ruff check + format run automatically on commit

## CI/CD

`.github/workflows/ci-cd.yml` runs on push/PR:
- **lint**: ruff check + format, `uv lock --check`, mypy, pip-audit (uses `--extra ml`)
- **container-scan**: builds Docker image and runs Trivy vulnerability scan (`scanners: vuln`, HIGH/CRITICAL fail gate)
- **unit-test**: pytest with coverage, uploads coverage artifact
- **integration-test**: Real PostgreSQL + pgvector service container, explicitly creates `vector` extension before Alembic migrations
- **deploy-modal**: Deploys Modal functions on main branch push (gates on lint + container-scan + unit-test + integration-test)
- `.github/workflows/codeql.yml` uses `github/codeql-action@v4` and skips upload gracefully when repository code scanning is disabled

## Gotchas

- `umap-learn` requires `numba>=0.59` for Python 3.12 (older numba fails to build)
- Tests must not hardcode values from `.env` (CI/CD has no `.env`) -- use `settings.*` dynamically
- DB `has_embedding` is integer (0/1), not boolean -- use `= 0` not `= false` in raw SQL
- DB enums use `StrEnum` -- SQLAlchemy sends `.name` (UPPERCASE) to the DB. DB enum values are **UPPERCASE**: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED` (JobStatus); `INGEST`, `CLUSTER_L1`, `CLUSTER_L2`, `CLUSTER_FULL`, `PIPELINE`, `GDRIVE_SYNC` (JobType). Use UPPERCASE in raw SQL.
- Pydantic Settings `extra: "ignore"` is set in config.py -- extra `PIC_*` env vars won't crash the app
- S3-compatible storage with Cloudflare R2 requires `region_name="auto"` in boto3 client (not a real AWS region)
- Modal functions use lazy imports inside function bodies so Modal secrets (env vars) are available before `settings` loads
- Modal secret is named `pic-env` -- contains all `PIC_*` env vars for workers
- Modal app name is `"pic"`
- Container host needs `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` env vars to dispatch Modal jobs from the API
- CI integration job runs Alembic against service Postgres and requires `CREATE EXTENSION IF NOT EXISTS vector` before migrations
- Pipeline/cluster workers use PostgreSQL advisory lock (`0x50494301`) -- concurrent runs will fail with 409
- `JobType.PIPELINE` and `JobType.GDRIVE_SYNC` are valid DB enum values (in addition to `CLUSTER_FULL`, etc.)
- `images.content_hash` column (SHA256) has a unique index -- duplicate content is rejected
- HNSW vector index exists on `embedding` column -- fast k-NN search, no need for brute-force scans
- Structured JSON logging in production -- request IDs tracked via `X-Request-ID` header
- `Product.tags` is stored as JSON text (not a native JSON column) -- serialize with `json.dumps()`, deserialize with `json.loads()`
- GDrive sync worker shares the same advisory lock (`0x50494301`) as pipeline -- they cannot run concurrently
- Modal cron `check_gdrive_for_new_files` runs every 15 min on a lightweight CPU image (no ML deps)
- GDrive sync requires both `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` and `PIC_GDRIVE_FOLDER_ID` -- endpoint returns 400 if missing

## Quality Gates

**IMPORTANT: Run ALL checks before committing. Do NOT commit if any check fails.**

1. `uv run ruff check src/ tests/ scripts/` -- zero errors
2. `uv run ruff format --check src/ tests/ scripts/` -- zero formatting issues
3. `uv run mypy src/pic/` -- zero type errors
4. `uv run pytest -m unit` -- all tests pass
5. `uv run pip-audit` -- no known vulnerabilities

## Code Standards

- Every new endpoint MUST have unit tests
- Every new service function MUST have type hints on all parameters and return values
- Every new API route MUST include proper error handling (try/except with appropriate HTTP status codes)
- Every database query MUST use parameterized queries (SQLAlchemy handles this, but never use raw f-strings for SQL)
- NEVER add TODO/FIXME without creating a corresponding GitHub issue
- NEVER import from internal modules using relative imports across package boundaries
- NEVER catch bare `except:` -- always catch specific exceptions

## Task Tracking

- All features, bugs, and improvements are tracked as GitHub Issues
- When discovering a new bug or improvement opportunity, create a GitHub Issue
- Reference issue numbers in commit messages (e.g. `fixes #42`)
- Do NOT leave TODOs in code without a corresponding GitHub Issue
- Before starting work, check open issues for context
