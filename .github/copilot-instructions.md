# GitHub Copilot Workspace Instructions

This file provides onboarding guidance for GitHub Copilot coding agents working with the NIC repository. Read this file first to understand how to work most efficiently with this codebase.

> **Note**: For comprehensive project documentation, see [AGENTS.md](../AGENTS.md). For Claude-specific guidance, see [CLAUDE.md](../CLAUDE.md).

## Project Overview

**NIC** is a hierarchical image clustering API for cake images (~10,000 images) with two-level clustering:

- **Level 1 (L1)**: Near-duplicate detection using perceptual hashing (pHash) to group images of the same product from different angles
- **Level 2 (L2)**: Semantic similarity clustering using DINOv2 embeddings + UMAP + HDBSCAN to group similar designs (e.g., all "superman" cakes)

**Tech Stack**: FastAPI + Modal (serverless GPU workers) + Neon PostgreSQL/pgvector + Cloudflare R2 + Railway (deployment)

**Key Architecture**: API on Railway, ML workers on Modal GPU instances, images in R2 object storage, metadata + vectors in Neon PostgreSQL with pgvector extension.

## Quick Start Commands

```bash
# Install dependencies (API only)
uv sync
# Install with ML deps (needed for workers/tests with embeddings)
uv sync --extra ml

# Run API locally (requires PostgreSQL with pgvector)
docker compose up db -d
uv run fastapi dev src/nic/main.py

# Run tests (use markers to run specific test groups)
uv run pytest -m unit          # Fast, no external deps
uv run pytest -m integration   # Requires Docker (testcontainers)
uv run pytest -m e2e           # Full pipeline, slow

# Lint and format
uv run ruff check src/ tests/ scripts/
uv run ruff format src/ tests/ scripts/

# Type check
uv run mypy src/nic/

# Security audit
uv run pip-audit

# Coverage (70% minimum threshold enforced)
uv run pytest -m unit --cov=src/nic --cov-report=term

# Database migrations
uv run alembic upgrade head                           # Apply pending migrations
uv run alembic revision --autogenerate -m "message"  # Generate migration from models

# Deploy Modal functions
modal deploy src/nic/modal_app.py

# Makefile shortcuts
make test      # Unit tests only
make test-all  # All tests
make lint      # Ruff check + format
make format    # Ruff format only
```

## Repository Structure

```
NIC/
├── src/nic/                     # Main application code
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Pydantic Settings (NIC_* env vars)
│   ├── modal_app.py             # Modal serverless GPU functions
│   ├── api/                     # FastAPI endpoints
│   │   ├── router.py            # Central route aggregation
│   │   ├── images.py            # Image CRUD + presigned URLs
│   │   ├── clusters.py          # L1/L2 cluster hierarchy
│   │   ├── search.py            # Semantic + duplicate search
│   │   ├── jobs.py              # Job status tracking
│   │   ├── products.py          # Product CRUD + candidates
│   │   ├── pipeline.py          # Batch ingest + dedup + cluster
│   │   ├── gdrive.py            # Google Drive sync trigger
│   │   └── deps.py              # Shared dependencies (get_db)
│   ├── services/                # Business logic layer
│   │   ├── embedding.py         # DINOv2 embeddings
│   │   ├── clustering.py        # L1 pHash + L2 UMAP/HDBSCAN
│   │   ├── clustering_pipeline.py  # Shared clustering logic
│   │   ├── vector_store.py      # pgvector k-NN search
│   │   ├── image_store.py       # R2 S3 operations
│   │   ├── modal_dispatch.py    # Modal job submission
│   │   └── gdrive.py            # Google Drive API wrapper
│   ├── models/                  # Database models + schemas
│   │   ├── db.py                # SQLAlchemy ORM models
│   │   └── schemas.py           # Pydantic request/response schemas
│   ├── worker/                  # Modal job entry points
│   │   ├── ingest.py            # Compute pHash + DINOv2
│   │   ├── cluster.py           # Run L1 + L2 clustering
│   │   ├── pipeline.py          # Unified discover+dedup+ingest+cluster
│   │   ├── gdrive_sync.py       # GDrive download + embed + cluster
│   │   ├── helpers.py           # Advisory lock + job lifecycle
│   │   └── entrypoint.py        # Shared worker logic
│   ├── core/                    # Infrastructure
│   │   ├── database.py          # SQLAlchemy async engine
│   │   ├── auth.py              # API key validation
│   │   ├── rate_limit.py        # slowapi rate limiting
│   │   └── logging.py           # Structured JSON logging
│   └── migrations/              # Alembic database migrations
├── tests/                       # Test suite
│   ├── conftest.py              # Shared pytest fixtures
│   ├── unit/                    # Fast unit tests (70+ tests)
│   ├── integration/             # PostgreSQL integration tests
│   └── e2e/                     # Full pipeline tests
├── scripts/                     # Utility scripts
│   ├── seed.py                  # Bulk image upload to R2
│   ├── visualize.py             # Generate cluster visualization
│   └── debt_sync.py             # Technical debt automation
├── docs/                        # Documentation
│   ├── operations/              # Runbooks (backup, restore, rollback)
│   ├── automation/              # Agent rules + plugin policy
│   ├── audit/                   # Technical debt register (148 items)
│   └── plans/                   # Design documents
├── .github/workflows/           # CI/CD pipelines
├── pyproject.toml               # Project metadata + quality config
├── Dockerfile                   # Multi-stage build (API + worker)
├── Dockerfile.railway           # Railway-optimized (API only, no ML)
└── docker-compose.yml           # Local dev stack (PostgreSQL + MinIO)
```

## Setup Instructions

### Prerequisites
- Python 3.12
- uv package manager
- Docker (for local PostgreSQL + integration tests)
- Modal account (for deploying GPU workers)

### Environment Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Required environment variables:
   - `NIC_DATABASE_URL` - PostgreSQL connection string
   - `NIC_S3_BUCKET` - Cloudflare R2 bucket name
   - `NIC_S3_ENDPOINT_URL` - R2 endpoint URL
   - `NIC_S3_ACCESS_KEY_ID` - R2 access key
   - `NIC_S3_SECRET_ACCESS_KEY` - R2 secret key

3. Optional environment variables:
   - `NIC_API_KEY` - API authentication (if empty, auth is disabled for dev)
   - `NIC_SENTRY_DSN` - Error tracking (empty = disabled)
   - `NIC_GDRIVE_SERVICE_ACCOUNT_JSON` - Google Drive sync (JSON string)
   - `NIC_GDRIVE_FOLDER_ID` - Google Drive folder to monitor
   - `NIC_RATE_LIMIT_DEFAULT` / `NIC_RATE_LIMIT_BURST` - Rate limiting config

### Local Development

```bash
# Start PostgreSQL with pgvector
docker compose up db -d

# Install dependencies
uv sync --extra ml

# Run database migrations
uv run alembic upgrade head

# Start API server
uv run fastapi dev src/nic/main.py
```

API documentation available at: http://localhost:8000/docs

## Code Standards

### Quality Gates (MUST pass before every commit)

1. **Linting**: `uv run ruff check src/ tests/ scripts/` — zero errors
2. **Formatting**: `uv run ruff format --check src/ tests/ scripts/` — zero issues
3. **Type checking**: `uv run mypy src/nic/` — zero type errors
4. **Tests**: `uv run pytest -m unit` — all tests pass
5. **Security**: `uv run pip-audit` — no known vulnerabilities

### Code Requirements

- **Type hints required**: Every new function MUST have type hints on all parameters and return values
- **Tests required**: Every new endpoint MUST have unit tests
- **Error handling**: Every API route MUST include proper error handling (try/except with appropriate HTTP status codes)
- **Async everywhere**: Use `async def` for all FastAPI routes, database operations, and I/O
- **Parameterized queries**: NEVER use f-strings for SQL, always use SQLAlchemy parameterized queries
- **No TODOs without issues**: NEVER add TODO/FIXME without creating a corresponding GitHub issue
- **Specific exceptions**: NEVER catch bare `except:` — always catch specific exceptions
- **No relative imports**: NEVER import across package boundaries using relative imports

### Pre-commit Hooks

The repository uses pre-commit hooks (`.pre-commit-config.yaml`):
- Ruff check + format run automatically on commit
- Unit tests run on pre-push

Install hooks: `pre-commit install`

## Testing Conventions

### Test Markers

Use pytest markers to run specific test groups:
- `@pytest.mark.unit` - Fast tests, no external dependencies
- `@pytest.mark.integration` - Requires PostgreSQL via testcontainers
- `@pytest.mark.e2e` - Full pipeline tests (slow, requires ML model)

### Coverage Requirements

- Minimum coverage: **70%** (enforced in CI)
- Run with: `uv run pytest -m unit --cov=src/nic --cov-report=term`

### Integration Test Fixtures

Available in `tests/integration/conftest.py`:
- `db` - Async SQLAlchemy session
- `client` - httpx AsyncClient for API testing
- `seed_images` - Helper to create test images
- `seed_l1_group` - Helper to create L1 groups
- `seed_l2_cluster` - Helper to create L2 clusters
- `seed_job` - Helper to create job records

### Important Testing Notes

- Integration tests use `testcontainers[postgres]` with `pgvector/pgvector:pg16` image
- Database connections use `NullPool` to avoid asyncpg event-loop binding errors
- **NEVER hardcode `.env` values in tests** — use `settings.*` dynamically (CI has no `.env`)
- Tests must work in CI environment without local configuration

## Critical Gotchas and Workarounds

### Database-Related

1. **Database enums are UPPERCASE**: DB enum values are `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `INGEST`, `CLUSTER_FULL`, `PIPELINE`, `GDRIVE_SYNC`. Use UPPERCASE in raw SQL queries.

2. **has_embedding is integer**: The `has_embedding` column is 0/1 (integer), NOT boolean. Use `= 0` not `= false` in raw SQL.

3. **All schema changes via migrations**: NEVER make direct changes to Neon DB. All schema changes MUST go through Alembic migrations.

4. **pgvector extension required**: Integration tests require explicit `CREATE EXTENSION IF NOT EXISTS vector` before running migrations.

### Deployment-Related

5. **No direct Railway deploys**: NEVER deploy to Railway directly. All deployments go through GitHub Actions CI/CD via push to main branch.

6. **No local Docker builds**: NEVER build/push Docker images locally. Push code to GitHub; Railway auto-deploys, Modal deploys via CI/CD.

7. **Dockerfile.railway specific**: Uses `--no-sync` flag on `uv run` CMD because appuser cannot modify root-owned venv.

### Worker-Related

8. **Advisory lock for concurrency**: Pipeline/cluster/gdrive workers use PostgreSQL advisory lock `0x4E494301`. Concurrent runs will fail with HTTP 409.

9. **Modal lazy imports**: Modal functions use lazy imports inside function bodies so Modal secrets (env vars) are available before `settings` loads.

10. **Modal secrets**: Modal secret is named `nic-env` and contains all `NIC_*` env vars needed by workers.

### Dependency Issues

11. **numba version**: `umap-learn` requires `numba>=0.59` for Python 3.12 (older versions fail to build).

12. **R2 region**: Cloudflare R2 requires `region_name="auto"` in boto3 client (not a real AWS region).

### Code Patterns

13. **FastAPI Depends in defaults**: FastAPI `Depends()`/`Query()` in defaults triggers ruff B008 — this rule is intentionally ignored.

14. **Product.tags storage**: `Product.tags` is stored as TEXT JSON (not JSONB) — serialize with `json.dumps()`, deserialize with `json.loads()`.

15. **GDrive sync requirements**: Both `NIC_GDRIVE_SERVICE_ACCOUNT_JSON` and `NIC_GDRIVE_FOLDER_ID` must be set for GDrive sync to work.

## Common Errors and Solutions

### Error: "asyncpg pool: Event loop is closed"

**Symptom**: Tests fail with asyncpg event loop errors.

**Solution**: Use `NullPool` in test database connections. This is already configured in `tests/integration/conftest.py`.

### Error: "relation 'vector' does not exist"

**Symptom**: Alembic migration fails with missing pgvector extension.

**Solution**: Run `CREATE EXTENSION IF NOT EXISTS vector` before migrations. CI integration tests do this automatically.

### Error: "Module 'torch' has no attribute..."

**Symptom**: Import errors when running workers locally.

**Solution**: Install ML dependencies with `uv sync --extra ml`. The API-only deployment uses `uv sync` without extras.

### Error: "Advisory lock could not be acquired"

**Symptom**: Pipeline or cluster job returns HTTP 409.

**Solution**: Another job is already running. Wait for it to complete or check job status with `GET /api/v1/jobs`.

### Error: "pytest collection failed: cannot find module"

**Symptom**: pytest cannot find test modules.

**Solution**: Ensure you're running pytest from repository root: `uv run pytest -m unit`

### Error: "Railway deployment failed: image too large"

**Symptom**: Deployment fails with image size > 4GB.

**Solution**: Use `Dockerfile.railway` which excludes ML dependencies. Railway auto-deploys using this file.

## CI/CD Workflow

### GitHub Actions Jobs

The `.github/workflows/ci-cd.yml` workflow runs on every push/PR:

1. **lint**: Ruff check/format, uv lock check, mypy, pip-audit
2. **debt-integrity**: Validates `TECHNICAL_DEBT.md` with `scripts/debt_sync.py`
3. **container-scan**: Builds `Dockerfile.railway`, runs Trivy scan (HIGH/CRITICAL vulnerabilities fail)
4. **unit-test**: Runs unit tests with 70% coverage requirement
5. **integration-test**: Runs integration tests with PostgreSQL service container
6. **deploy-modal**: Deploys Modal functions on main branch (gates on all prior jobs)

### Other Workflows

- **codeql.yml**: SAST analysis with `github/codeql-action@v4` (gracefully skips when repo scanning disabled)
- **deploy-staging.yml**: Optional staging deployment
- **debt-register-audit.yml**: Weekly technical debt audit

### Deployment Process

- **Railway**: Auto-deploys from main branch (no manual step needed)
- **Modal**: Deploys via CI `deploy-modal` job on main branch
- **NEVER deploy manually** — always push to GitHub and let CI/CD handle deployment

## Technical Debt Highlights

The repository maintains a detailed technical debt register in `TECHNICAL_DEBT.md` with 148 tracked items. Key highlights:

### Critical Issues (9 total)

- **C1**: Cluster hierarchy N+1 loads 25k+ Image records (performance impact)
- **C2**: Pipeline downloads all S3 images before DB dedup check (waste ~1.8GB on duplicates)
- **C3**: No database backup/restore strategy documented
- **C4-C9**: Six critical test coverage gaps

### High-Priority Quick Wins (8 items, minimal effort)

- Fix `Dockerfile.railway` healthcheck (use stdlib `urllib.request` instead of `httpx`)
- Add composite index `ix_jobs_status_created_at`
- Add `Retry-After` header on 429 responses
- Add `Location` header on 201/202 responses
- Use `np.float32` for embeddings (halves memory usage)
- Fix GDrive `_processed_folder_cache` thread safety
- Fix hardcoded `l1_group_id=0` in visualization
- Optimize L2 query to project only needed columns

### Performance Issues (7 high-priority)

- Duplicate search scans 1000 images in-memory with O(n) Hamming distance
- Connection pool too small (15 max) for concurrent workers + API
- Product images endpoint generates presigned URLs serially (100 boto3 calls)
- GDrive sync downloads files serially within batch

### Security Issues (2 high-priority)

- PostgreSQL should use `sslmode=verify-full` in production
- `/health/detailed` exposed without authentication (leaks metrics)

### Architecture Issues (4 high-priority)

- ~150 lines duplicated across pipeline/gdrive_sync/ingest workers
- God modules: `pipeline.py` (363 lines), `gdrive_sync.py` (269 lines)
- Missing abstraction for advisory lock management

See `TECHNICAL_DEBT.md` for complete details, effort estimates, and GitHub issue references.

## Architecture Flows

### Ingestion Flow

1. Images uploaded to R2 `images/` prefix via `scripts/seed.py`
2. Modal `run_ingest` function triggered
3. Compute perceptual hash (pHash) + DINOv2 embedding (768-dim)
4. Store metadata in Neon PostgreSQL
5. Move image from `images/` to `processed/` in R2

**Note**: Ingestion does NOT auto-cluster. Clustering is a separate step.

### Clustering Flow

1. Trigger via `POST /api/v1/clusters/run` or automatically by `seed.py`
2. Modal `run_cluster` function executes on GPU
3. **Level 1**: Group by pHash similarity (near-duplicates)
4. **Level 2**: UMAP dimensionality reduction (768→25D) + HDBSCAN clustering on reduced embeddings
5. Store cluster assignments in database

### Pipeline Flow (for n8n integration)

1. Trigger via `POST /api/v1/pipeline/run`
2. Acquire PostgreSQL advisory lock (prevents concurrent runs)
3. Discover images in R2 `images/` prefix
4. Deduplicate via SHA256 content hash (moves duplicates to `rejected/`)
5. Ingest new images (pHash + DINOv2)
6. Run full clustering (L1 + L2)
7. Release advisory lock

### Product Flow (post-clustering)

1. After clustering, L1 groups become product candidates
2. `GET /api/v1/products/candidates` lists unprocessed L1 groups
3. AI (via n8n) generates title/description/tags
4. `POST /api/v1/products` creates product from L1 group
5. Full CRUD available on `/api/v1/products`

### Google Drive Sync Flow

1. Modal cron runs every 15 min (CPU tier, lightweight check)
2. If new images found in GDrive folder → spawn GPU worker
3. Download images from GDrive
4. Compute SHA256 hash for deduplication
5. Compute pHash + DINOv2 embeddings
6. Upload to R2
7. Move processed files to GDrive `processed/` subfolder
8. Run clustering

## API Authentication

- API key via `X-API-Key` header on all `/api/v1/*` routes
- Set `NIC_API_KEY` env var
- If `NIC_API_KEY` is empty/unset, authentication is disabled (dev mode)
- Uses timing-safe comparison (`secrets.compare_digest`)

## Health Checks

- `GET /health` - Basic health check (used by Railway readiness probes)
- `GET /health/detailed` - DB connectivity + recent job failures + connection pool metrics

**Security note**: `/health/detailed` is currently exposed without auth (see H-S2 in technical debt).

## Rate Limiting

- Configured via `NIC_RATE_LIMIT_DEFAULT` (requests per minute)
- Configured via `NIC_RATE_LIMIT_BURST` (burst allowance)
- Uses slowapi library
- Applied to all API routes

## Observability

### Logging

- Structured JSON logging in production
- Request IDs tracked via `X-Request-ID` header
- Log level configurable via environment

### Metrics

- Prometheus metrics exposed automatically via `prometheus-fastapi-instrumentator`
- Metrics endpoint: `/metrics`
- **Note**: Metrics are exposed but not currently scraped (see H-DO4)

### Error Tracking

- Sentry integration available (set `NIC_SENTRY_DSN`)
- If `NIC_SENTRY_DSN` is empty, error tracking is disabled

## Database Operations

### Migrations

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Generate migration from model changes
uv run alembic revision --autogenerate -m "description"

# Rollback one migration
uv run alembic downgrade -1
```

### Backup/Restore

See `docs/operations/database-backup-restore.md` for detailed runbook.

Quick reference:
```bash
# Create logical backup
make backup-db NIC_POSTGRES_URL="$NIC_POSTGRES_URL"

# Restore from backup
make restore-db NIC_POSTGRES_URL="$NIC_POSTGRES_URL" BACKUP_FILE=backups/file.sql
```

## Working with Images

### R2 Object Storage Prefixes

- `images/` - Inbox for new images (ingestion source)
- `processed/` - Successfully ingested images
- `rejected/` - Duplicate images (detected by pipeline)

### Presigned URLs

- Generated on-demand for image access
- Valid for 15 minutes (configurable)
- No caching implemented (see M-P5 in technical debt)

## Modal Serverless GPU

### Functions

- `run_ingest` - Compute pHash + DINOv2 embeddings
- `run_cluster` - Full L1 + L2 clustering
- `run_pipeline` - Unified discover+dedup+ingest+cluster
- `run_gdrive_sync` - Google Drive → R2 sync with clustering
- `check_gdrive_for_new_files` - Cron job (every 15 min) to check GDrive

### Deployment

```bash
# Deploy all functions
modal deploy src/nic/modal_app.py

# Or let CI/CD handle it (preferred)
git push origin main
```

### Secrets

Modal secrets stored in `nic-env` secret:
- All `NIC_*` environment variables needed by workers
- Configure at: https://modal.com/secrets

## Development Workflow

1. **Create a branch**: `git checkout -b feature/your-feature`
2. **Make changes**: Follow code standards and conventions
3. **Run quality gates**: Lint, format, type check, test
4. **Commit**: Pre-commit hooks will run automatically
5. **Push**: CI will run all checks
6. **Create PR**: CI must pass before merge
7. **Merge to main**: Triggers automatic deployment to Railway + Modal

## Task Tracking

- All features, bugs, improvements tracked as GitHub Issues
- Reference issue numbers in commit messages: `fixes #42`
- Do NOT leave TODOs without corresponding GitHub Issue
- Check open issues for context before starting work

## Performance Considerations

- **Connection pool**: Current size may be insufficient for concurrent workers (15 max)
- **N+1 queries**: Be aware of cluster hierarchy eager loading (see C1)
- **Presigned URLs**: Generated serially, consider batching for large lists
- **Vector search**: HNSW index uses defaults, may need tuning for accuracy
- **Memory usage**: Use `np.float32` for embeddings when possible (halves memory)

## Security Best Practices

- **Never commit secrets**: Use `.env` file (gitignored)
- **Use environment variables**: All config via `NIC_*` env vars
- **Parameterized queries**: Always use SQLAlchemy, never f-strings
- **API key authentication**: Enable in production via `NIC_API_KEY`
- **SSL for database**: Use `sslmode=verify-full` in production
- **Input validation**: Pydantic schemas validate all API inputs

## Additional Resources

- **Full documentation**: [AGENTS.md](../AGENTS.md)
- **Claude-specific**: [CLAUDE.md](../CLAUDE.md)
- **Technical debt**: [TECHNICAL_DEBT.md](../TECHNICAL_DEBT.md)
- **Operations runbooks**: `docs/operations/`
- **Design documents**: `docs/plans/`
- **n8n integration**: `docs/n8n-setup-guide.md`

## Getting Help

If you encounter issues or need clarification:

1. Check existing GitHub Issues
2. Review documentation in `docs/`
3. Check `TECHNICAL_DEBT.md` for known issues
4. Review `AGENTS.md` for comprehensive details
5. Create a new GitHub Issue if needed

---

**Last Updated**: 2026-02-17

**Maintained by**: Repository maintainers

**Questions?**: Open a GitHub Issue
