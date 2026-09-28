# PIC -- Hierarchical Image Clustering API

> **Note for human contributors:** This file provides structured context for AI
> coding assistants (Claude Code, Cursor, GitHub Copilot Workspace, etc.). You
> can safely ignore it -- everything here is also covered in
> [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the docs.

This file provides context and instructions for AI coding agents working with this repository.

## Project Overview

PIC is an open-source hierarchical image clustering API for product catalog images, meant to be self-hosted by anyone. Two-level clustering:
- **Level 1**: Near-duplicate detection (same product, different angles) via HDBSCAN on DINOv2 cosine distance
- **Level 2**: Semantic similarity (visually similar products) via DINOv2 embeddings + UMAP + HDBSCAN

## Commands

```bash
# Install dependencies (API only)
uv sync
# Install with ML deps (needed for workers/tests with embeddings)
uv sync --extra ml

# Full local stack: db + api (migrates on start) + local worker; images go in data/images/
mkdir -p data/images && docker compose up --build -d

# Run API locally (requires PostgreSQL with pgvector)
docker compose up db -d
uv run fastapi dev src/pic/main.py

# Run the local worker natively (uses the Apple GPU on macOS)
uv run pic-worker

# Run tests
uv run pytest -m unit          # Fast, no external deps
uv run pytest -m integration   # Requires PostgreSQL: docker compose up db -d
uv run pytest -m e2e           # Full pipeline, slow
uv run pytest                  # All tests

# Lint
uv run ruff check src/ tests/ scripts/
uv run ruff format src/ tests/ scripts/

# Type check
uv run mypy src/pic/

# Security audit
uv run pip-audit --skip-editable

# Coverage (70% minimum threshold)
uv run pytest -m unit --cov=src/pic --cov-report=term

# Deploy Modal functions
modal deploy src/pic/modal_app.py

# Database migrations (Alembic)
uv run alembic upgrade head                    # Apply all pending migrations
uv run alembic revision --autogenerate -m "description"  # Generate migration from model changes

# Upload a folder to the storage inbox, run the pipeline, wait for it (uses PIC_* storage settings)
python scripts/seed.py /path/to/images/
python scripts/seed.py /path/to/images/ --no-cluster  # Upload only
```

A `Makefile` provides shortcuts: `make dev`, `make test`, `make test-all`, `make lint`, `make format`, `make migrate`, `make seed DIR=/path`, `make audit`.

## Architecture

**Deployment**: API container + workers (local `pic-worker` by default, or Modal serverless GPU) + object storage (local, S3-compatible or GCS) + PostgreSQL/pgvector (metadata + vectors)

**Job flow**: the API creates a job row with its `params`, then `dispatch_job()` either leaves it PENDING for `pic-worker` (`PIC_WORKER_BACKEND=local`, default) or spawns the matching Modal function (`modal`). `pic-worker` claims jobs with `FOR UPDATE SKIP LOCKED`, runs one at a time, and on start fails RUNNING local jobs left by a crashed worker. There is no per-image ingest job: the pipeline discovers, dedups, ingests and clusters.

**Clustering flow**: Separate from ingestion. Triggered via `POST /api/v1/clusters/run` or automatically by `seed.py` after upload. Runs UMAP + HDBSCAN on all images with embeddings. Ingestion does NOT auto-cluster.

**Pipeline flow** (n8n integration): `POST /api/v1/pipeline/run` -- single endpoint that discovers images in S3 `images/`, deduplicates via SHA256 content hash, ingests (pHash + DINOv2), then clusters. Duplicates moved to `rejected/`. Uses PostgreSQL advisory lock to prevent concurrent runs.

**Product flow** (post-clustering): After clustering, L1 groups become product candidates. `GET /api/v1/products/candidates` lists unprocessed L1 groups. AI (via n8n) generates title/description/tags, then `POST /api/v1/products` creates a product from an L1 group, linking all member images. Full CRUD on `/api/v1/products`.

**Auth**: API key via `X-API-Key` header on all `/api/v1/*` routes. Set `PIC_API_KEY` for protected mode; if it is unset, routes return 503 unless `PIC_AUTH_DISABLED=true` explicitly opts into unauthenticated mode. Uses timing-safe comparison.

**Web UI**: Server-rendered at `/ui` (Jinja2 + htmx, no build step). With `PIC_API_KEY` set, `/ui/login` sets a signed `pic_session` cookie accepted only by `/ui` routes; UI POSTs require the `HX-Request` header. Products are the durable curation unit; clustering never changes them.

**Health checks**: `GET /health` (basic) and `GET /health/detailed` (DB connectivity + recent job failures).

**R2 lifecycle**: `images/` is an inbox; after successful ingest, objects move to `processed/`. Duplicates (detected by pipeline) move to `rejected/`.

**Google Drive sync flow**: `POST /api/v1/gdrive/sync` or automatic via Modal cron (every 15 min). Tier 1 (CPU cron) checks GDrive for new images -> if found, spawns Tier 2 (GPU worker) that downloads images, computes hashes + embeddings, uploads to S3, moves processed files to GDrive `processed/` subfolder, then runs clustering. Uses same advisory lock as pipeline.

**Key tech choices**: DINOv2 (visual similarity without text bias), pgvector (single DB for metadata + vectors), UMAP + HDBSCAN (60% quality gain over raw high-dim clustering), HDBSCAN on DINOv2 cosine distance for L1 (density-based near-duplicate grouping), pHash for duplicate search API, Modal (serverless GPU).

## Code Structure

- `src/pic/main.py` -- FastAPI application entry point (lifespan + wiring only)
- `src/pic/api/` -- FastAPI endpoints (images, clusters, search, jobs, products, gdrive)
- `src/pic/api/health.py` -- Health check endpoints (`/health`, `/health/detailed`)
- `src/pic/api/pipeline.py` -- Pipeline endpoint for n8n (batch ingest + dedup + cluster)
- `src/pic/api/products.py` -- Product CRUD + candidate listing for AI tagging workflow
- `src/pic/api/deps.py` -- Shared FastAPI dependencies (get_db session)
- `src/pic/api/router.py` -- Central router combining all endpoint routers
- `src/pic/api/gdrive.py` -- Google Drive sync trigger endpoint
- `src/pic/services/` -- Business logic (embedding, clustering, vector_store, image_store, dispatch, modal_dispatch, gdrive)
- `src/pic/services/dispatch.py` -- Routes new jobs to the local or Modal backend
- `src/pic/services/clustering_pipeline.py` -- Shared clustering logic used by both cluster and pipeline workers
- `src/pic/services/gdrive.py` -- Google Drive API wrapper (list, download, move files)
- `src/pic/services/curation.py` -- Product membership changes (create, add, remove, split, merge), shared by UI and API
- `src/pic/services/browse.py` -- Paged read models for UI pages
- `src/pic/ui/` -- Web UI: Jinja2 templates + vendored htmx, cookie session auth (`routes.py`, `auth.py`)
- `src/pic/models/` -- SQLAlchemy models (`db.py`) and Pydantic schemas (`schemas.py`)
- `src/pic/worker/` -- Job implementations shared by both backends (cluster, pipeline, url_ingest, gdrive_sync)
- `src/pic/worker/local_runner.py` -- `pic-worker`: claims PENDING jobs and runs them in-process
- `src/pic/worker/pipeline.py` -- Pipeline worker (discover, dedup, ingest, cluster)
- `src/pic/worker/gdrive_sync.py` -- Google Drive -> S3 sync worker (download, dedup, embed, cluster)
- `src/pic/worker/helpers.py` -- Advisory lock, job status helpers (`acquire_advisory_lock`, `mark_job_running/failed/completed`)
- `src/pic/modal_app.py` -- Modal app definition (GPU functions for ingest, clustering, gdrive sync + CPU cron for gdrive check)
- `src/pic/config.py` -- Pydantic Settings (all `PIC_*` env vars)
- `src/pic/core/` -- Database engine, structured JSON logging, API key auth, middleware, exception handlers
- `src/pic/migrations/` -- Alembic migrations (uses `sync_database_url` from config)
- `scripts/seed.py` -- Bulk image upload + optional auto-clustering
- `docs/n8n-setup-guide.md` -- n8n integration setup documentation
- `docs/n8n-workflows/` -- n8n workflow JSON exports (batch Google Drive upload)

## Setup

Copy `.env.example` to `.env` and fill in values. Key vars: `PIC_DATABASE_URL`, `PIC_S3_BUCKET`, `PIC_S3_ENDPOINT_URL`, `PIC_S3_ACCESS_KEY_ID`, `PIC_S3_SECRET_ACCESS_KEY`.

Observability: Prometheus metrics are exposed at `/metrics` via `prometheus-fastapi-instrumentator`; that endpoint uses the same auth dependency unless `PIC_AUTH_DISABLED=true`.

Optional Google Drive sync: `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` (service account JSON string), `PIC_GDRIVE_FOLDER_ID` (folder to watch). Both must be set to enable GDrive sync. OAuth scopes configurable via `PIC_GDRIVE_SCOPES` (default: `["https://www.googleapis.com/auth/drive"]`; use `drive.readonly` if move-to-processed is not needed).

For Modal: run `modal setup` to authenticate, then `modal deploy src/pic/modal_app.py`.

## Conventions

- Async everywhere (asyncpg, SQLAlchemy async sessions)
- Pydantic Settings for config (env prefix `PIC_`, loaded from `.env`)
- Ruff for linting (B008 ignored -- FastAPI Depends pattern)
- mypy for type checking (`strict = true`, `pydantic.mypy` plugin)
- pytest markers: `unit`, `integration`, `e2e`
- Integration tests run against whatever `PIC_DATABASE_URL` points at (local `docker compose up db`, or the CI service container) using `NullPool` to avoid asyncpg event-loop binding errors
- Key integration fixtures: `db` (async session), `client` (httpx AsyncClient), `seed_images`, `seed_l1_group`, `seed_l2_cluster`, `seed_job`
- pgvector `Vector(768)` column type for DINOv2 embeddings
- L1/L2 naming: L1 = near-duplicate groups, L2 = semantic clusters
- Pre-commit hooks configured (`.pre-commit-config.yaml`): ruff check + format on commit, mypy on commit, unit tests on push. Keep its ruff `rev` equal to the ruff version in `uv.lock`

## CI/CD

`.github/workflows/ci-cd.yml` is the only workflow. Four jobs:
- **lint**: ruff check + format, `uv lock --check`, mypy, pip-audit (uses `--extra ml`)
- **unit**: pytest unit tests with 70% coverage floor
- **integration**: real PostgreSQL + pgvector service container (`pgvector/pgvector:pg18`), creates the `vector` extension, runs Alembic, then integration tests
- **deploy-modal**: on `main` only, after the other three pass; skipped with a notice when `MODAL_TOKEN_ID` is not set

GitHub Actions are pinned to a full commit SHA with the version in a trailing comment (`actions/checkout@<sha> # v7.0.1`); the repo's Actions policy rejects tag references, and Dependabot bumps the SHAs. The uv version is pinned once via the `UV_VERSION` env at the top of the workflow. CodeQL code scanning is disabled for this repo (turned off 2026-09-28); security checks are `pip-audit` in CI and code review. The repo's Actions policy only allows actions owned by `masa-57`, created by GitHub, or matching an allowlist (`actions/*`, `astral-sh/setup-uv`, `aquasecurity/*`); a new third-party action needs the allowlist updated in repo settings first, or the run fails with `startup_failure`. Dependabot (`.github/dependabot.yml`) opens one grouped PR per month for Python deps and one for Actions.

## Dependency Policy

**Run on the latest stable release of every dependency and tool** (Python packages, GitHub Actions, Docker base images, uv, ruff, mypy, Postgres). Staying behind needs a one-line comment saying why, next to the pin.

- Refresh with `uv lock --upgrade`, never a targeted bump, then run all quality gates
- When a workflow is edited, bump action SHAs to the latest release (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`)
- Lower bounds in `pyproject.toml` are deliberately loose; `uv.lock` is the source of truth
- Known exception: `requires-python = ">=3.12,<3.13"`. Moving to 3.13+ is untested against the `umap-learn` / `numba` / `torch` stack; try it when touching the ML deps

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
- With `PIC_WORKER_BACKEND=modal`, the API host needs `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` to dispatch Modal jobs. The default is `local`: existing Modal deployments must set `modal` explicitly
- `pic-worker` refuses to start unless `PIC_WORKER_BACKEND=local`, so a job never runs on both backends
- The initial migration creates the `vector` extension, so a fresh database migrates with `alembic upgrade head` alone. The DB role needs permission to create extensions
- Sync DB URLs (Alembic, migration tests) must say `postgresql+psycopg2://` explicitly. SQLAlchemy 2.1 maps a bare `postgresql://` to psycopg 3, which is not installed. `pic.core.db_url.migration_url` forces `sslmode=verify-full` for non-localhost hosts unless the URL says `sslmode=disable` (compose does)
- Pipeline/cluster workers use PostgreSQL advisory lock (`0x4E494301`) -- concurrent runs will fail with 409
- `JobType.PIPELINE` and `JobType.GDRIVE_SYNC` are valid DB enum values (in addition to `CLUSTER_FULL`, etc.)
- `images.content_hash` column (SHA256) has a unique index -- duplicate content is rejected
- HNSW vector index exists on `embedding` column -- fast k-NN search, no need for brute-force scans
- Structured JSON logging in production -- request IDs tracked via `X-Request-ID` header
- `Product.tags` is stored as native PostgreSQL JSONB -- treat it as structured JSON, not serialized text
- GDrive sync worker shares the same advisory lock (`0x4E494301`) as pipeline -- they cannot run concurrently
- Modal cron `check_gdrive_for_new_files` runs every 15 min on a lightweight CPU image (no ML deps)
- GDrive sync requires both `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` and `PIC_GDRIVE_FOLDER_ID` -- endpoint returns 400 if missing

## Quality Gates

**IMPORTANT: Run ALL checks before committing. Do NOT commit if any check fails.**

1. `uv run ruff check src/ tests/ scripts/` -- zero errors
2. `uv run ruff format --check src/ tests/ scripts/` -- zero formatting issues
3. `uv run mypy src/pic/` -- zero type errors
4. `uv run pytest -m unit` -- all tests pass
5. `uv run pip-audit --skip-editable` -- no known vulnerabilities

## Code Standards

- Every new endpoint MUST have unit tests
- Every new service function MUST have type hints on all parameters and return values
- Every new API route MUST include proper error handling (try/except with appropriate HTTP status codes)
- Every database query MUST use parameterized queries (SQLAlchemy handles this, but never use raw f-strings for SQL)
- NEVER add TODO/FIXME without creating a corresponding GitHub issue
- NEVER import from internal modules using relative imports across package boundaries
- NEVER catch bare `except:` -- always catch specific exceptions

## Task Tracking

- All work is tracked as GitHub Issues in the current milestone (see `ROADMAP.md` for the order of work). Check the milestone before starting anything
- Simplification is a standing goal: when touching a module, remove settings, deps, or features that a small self-hosted deployment will never need. Prefer deleting over abstracting. Log larger candidates on the `simplification`-labelled issues rather than doing them by surprise
- PIC is open source and stays that way. Simplify for a small self-hosted deployment, not for a single private user: keep what outside users and contributors need (README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md, issue templates, self-hosting docs). When dropping a feature someone may rely on in a public deployment, document the alternative and note it in CHANGELOG
- When discovering a new bug or improvement opportunity, create a GitHub Issue and attach it to the milestone
- Reference issue numbers in commit messages (e.g. `fixes #42`)
- Do NOT leave TODOs in code without a corresponding GitHub Issue
