# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Web UI curation: make products from groups, add to, remove from, split and merge products, edit and delete products (#113)
- `POST /api/v1/images/upload`: multipart upload of images to the storage inbox (#113)
- Web UI at `/ui` to browse clusters and start runs (upload any local folder from the browser, storage inbox, Google Drive or URLs) with live progress and time estimates, plus a login page when `PIC_API_KEY` is set (#113)
- Product curation API: create a product from several L1 groups (`l1_group_ids`), add images or groups to a product, remove images, split and merge products. Products are never changed by re-clustering (#113)
- Local worker backend: `pic-worker` runs jobs from Postgres; `docker compose up` gives a full stack with no cloud accounts (#112)
- `PIC_WORKER_BACKEND` setting (`local` default, `modal`) and `jobs.params` column (#112)

### Changed
- Documentation rewritten for the web UI and local-first setup: README, architecture diagram, AGENTS.md, CONTRIBUTING, SECURITY, deployment and operations guides; `.env.example` now defaults to the Compose database and local storage (#113)
- **Breaking:** jobs no longer go to Modal by default. Existing Modal deployments must set `PIC_WORKER_BACKEND=modal` (#112)
- `scripts/seed.py` uploads through the storage backend and triggers the pipeline API; the old script was broken (#112)
- `psycopg2-binary` is a runtime dependency so migrations run in the API image
- The initial migration creates the pgvector extension; CI no longer does it by hand
- Refresh all dependencies to latest stable (FastAPI 0.141, Starlette 1.7, SQLAlchemy 2.1, transformers 5.17, torch 2.14); pip-audit is clean (#111)
- CI reduced to one workflow with four jobs: lint, unit, integration, deploy-modal; actions pinned to release SHAs (#116)
- Dependabot now opens one grouped PR per month for Python and one for Actions (#117)
- Local and CI Postgres moved to `pgvector/pgvector:pg18`

### Removed
- `docs/images/pipeline-demo.svg` (described AI tagging and Gemini, which PIC does not have)
- Old HTML cluster page `GET /api/v1/clusters/view` (now redirects to `/ui`), `scripts/visualize.py` and `scripts/visualize_clusters.py` (#113)
- CORS settings `PIC_CORS_ORIGINS` and `PIC_CORS_ALLOW_CREDENTIALS`; the UI is same-origin. Add CORS headers at a reverse proxy if a browser app on another origin calls the API (#119)
- Built-in rate limiting (`slowapi`) and its settings `PIC_RATE_LIMIT_DEFAULT`, `PIC_RATE_LIMIT_BURST`, `PIC_RATE_LIMIT_STORAGE_URL`, `PIC_JOB_TRIGGER_RATE_LIMIT`, plus the `X-RateLimit-Limit` header. Rate-limit at a reverse proxy instead; see `docs/deployment/self-hosted.md` (#120)
- Sentry integration (`sentry-sdk`, `PIC_SENTRY_DSN`) (#120)
- Railway config (`railway.json`) and its runbook; the API image runs on any container host (#118)
- Dead `ix_images_one_product_per_l1` conflict handling in `POST /api/v1/products` (the index was dropped in migration 012)
- Single-image ingest path (`run_ingest` Modal function, `pic.worker.ingest`, worker CLI entrypoint) (#112)
- MinIO from docker compose; local storage replaces it
- Unused dev dependencies `moto`, `testcontainers`, `coverage` (#117)
- Trivy container scan, docs-only CI filter, coverage aggregation, deploy-readiness, post-deploy smoke, and rollback jobs (#116)
- `TECHNICAL_DEBT.md`, completed design/plan docs under `docs/plans/`, the staging
  deployment workflow, and the staging environment guide. Work is now tracked in the
  `v0.3 Reboot` milestone; see `ROADMAP.md`.

### Fixed
- URL-ingested images are now embedded and clustered: the pipeline ingests existing `images/` rows without an embedding instead of rejecting them, and URLs without an extension get one from the image format (#128)
- A pipeline run where every image fails to ingest now ends `FAILED`; partial failures complete with the error count in the job's `error` field (#129)

## [0.2.1] - 2026-03-16

### Added
- Background job lifecycle metrics for ingest, clustering, pipeline, and Google Drive sync workers

### Fixed
- Restore URL-ingest Modal dispatch and follow-up job chaining (#54)
- Block SSRF-style URL-ingest targets across direct requests, DNS resolution, and redirect hops (#49)
- Require explicit auth opt-out instead of silently disabling auth when `PIC_API_KEY` is unset (#50)

### Changed
- Document authenticated `/metrics` behavior and align monitoring docs with the live Prometheus metric set (#52)
- Reconcile README, deployment guides, Google Drive setup docs, and contributor guidance with the current runtime behavior (#53)
- Skip docs-only CI runs and skip Modal deployment when Modal secrets are not configured (#45)

## [0.2.0] - 2026-03-15

### Added
- Pluggable storage backend system with `StorageBackend` Protocol
- S3 storage backend (default, wraps existing boto3 integration)
- Google Cloud Storage backend (`PIC_STORAGE_BACKEND=gcs`)
- Local filesystem storage backend (`PIC_STORAGE_BACKEND=local`) with automatic static file serving
- URL-based image ingestion endpoint (`POST /api/v1/images/ingest`) with rate limiting
- URL ingest worker with concurrent downloads, content validation, and deduplication
- `source_url` column on images table to track original image URLs
- Alembic migration for `source_url` column
- Integration tests for URL ingest endpoint

### Fixed
- Support shared rate limit storage for multi-instance deployments (#17)
- Make Google Drive OAuth scopes configurable (#8)

### Changed
- Split `main.py` into `core/middleware.py`, `core/exception_handlers.py`, and `api/health.py`
- Refactored `image_store.py` to delegate to pluggable `StorageBackend` instead of direct boto3 calls

## [0.1.0] - 2026-02-24

### Added
- Initial open-source release of PIC (Product Image Clustering)
- Two-level hierarchical clustering: HDBSCAN on DINOv2 cosine distance (L1) + UMAP/HDBSCAN on DINOv2 embeddings (L2)
- FastAPI REST API with image, cluster, product, search, and pipeline endpoints
- Modal serverless GPU workers for embedding generation and clustering
- Google Drive sync integration for automated image ingestion
- PostgreSQL with pgvector backend for vector similarity search
- S3-compatible object storage support (tested with Cloudflare R2)
- Pipeline API for end-to-end workflows: discover, deduplicate, ingest, cluster
- API key authentication
- Alembic database migrations
- Comprehensive test suite (unit + integration)
- Docker Compose for local development
- CI/CD pipeline with GitHub Actions

[0.2.1]: https://github.com/masa-57/pic/releases/tag/v0.2.1
[0.2.0]: https://github.com/masa-57/pic/releases/tag/v0.2.0
[0.1.0]: https://github.com/masa-57/pic/releases/tag/v0.1.0
