# Medium-Priority Technical Debt Resolution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve all 53 open GitHub issues labeled `Priority:Medium` across 6 parallel tracks.

**Architecture:** 22 issues are already fixed in code (waves 1-3) and just need GitHub closure + debt register updates. The remaining 31 issues span testing, performance, API design, architecture, code quality, DevOps, and security — organized into 5 independent parallel tracks that touch non-overlapping files.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pgvector, Modal, pytest, Alembic, GitHub CLI (`gh`)

---

## Track Overview

| Track | Issues | Parallelizable | Effort |
|-------|--------|----------------|--------|
| 0: Triage & Close Fixed Issues | 22 | N/A (batch) | Small |
| 1: Testing Improvements | 5 | Yes (with 2-5) | Medium |
| 2: Performance Optimizations | 3 | Yes (with 1,3-5) | Medium |
| 3: API Design Enhancements | 9 | Yes (with 1,2,4,5) | Large |
| 4: Architecture & Code Quality | 7 | Yes (with 1-3,5) | Large |
| 5: DevOps & Security | 5 | Yes (with 1-4) | Medium |

**Dependency:** Track 0 runs first (5 min). Tracks 1-5 are fully independent and can run in parallel.

---

## Track 0: Triage & Close Already-Fixed Issues

**22 issues already resolved in code — close on GitHub and update debt register.**

These issues were fixed in waves 1-3 but their GitHub issues remain open.

### Task 0.1: Verify and Close Fixed Issues

**Files:**
- Modify: `docs/audit/debt_register_148.csv` (update status for any remaining discrepancies)

**Step 1: Close all 22 already-fixed GitHub issues**

Run the following `gh` commands to close each issue with a note:

```bash
# Performance (already fixed)
gh issue close 152 -c "Already fixed: ix_images_s3_key index exists in models/db.py" -R masa-57/NIC
gh issue close 155 -c "Already fixed: lru_cache(maxsize=1024) on generate_presigned_url" -R masa-57/NIC

# Security (already fixed)
gh issue close 157 -c "Already fixed: SHA256-hashed API key prefix for rate limit bucket key in rate_limit.py" -R masa-57/NIC
gh issue close 159 -c "Already fixed: model_validator blocks cors_origins=['*'] when api_key is set" -R masa-57/NIC

# Code Quality (already fixed)
gh issue close 128 -c "Already fixed: ADVISORY_LOCK_ID centralized in core/constants.py" -R masa-57/NIC
gh issue close 133 -c "Already fixed: narrowed to modal.exception.Error in worker/helpers.py" -R masa-57/NIC
gh issue close 135 -c "Already fixed: config consistently uses empty string defaults" -R masa-57/NIC

# Database (already fixed)
gh issue close 137 -c "Already fixed: _batched_update helper with 5000-row chunks in clustering_pipeline.py" -R masa-57/NIC
gh issue close 138 -c "Already fixed: CheckConstraint ck_has_embedding_consistency in models/db.py" -R masa-57/NIC

# API Design (already fixed)
gh issue close 122 -c "Already fixed: X-RateLimit-Limit header added in access_log_middleware" -R masa-57/NIC
gh issue close 124 -c "Already fixed: custom RequestValidationError handler normalizes 422 responses in main.py" -R masa-57/NIC
gh issue close 115 -c "Already fixed: expires_in field added to ImageFileOut schema" -R masa-57/NIC

# DevOps (already fixed)
gh issue close 143 -c "Already fixed: BuildKit syntax directive + --mount=type=cache for uv in Dockerfile.railway" -R masa-57/NIC
gh issue close 148 -c "Already fixed: modal.Retries added to all 5 Modal function decorators" -R masa-57/NIC
gh issue close 150 -c "Already fixed: stale_job_timeout_minutes=90 exceeds Modal 60min timeout" -R masa-57/NIC
gh issue close 142 -c "Already fixed: pre-commit mypy now uses local hook via uv run matching CI" -R masa-57/NIC

# Testing (already fixed)
gh issue close 164 -c "Already fixed: sample_phash extended to 64 hex chars + sample_phash_alt fixture" -R masa-57/NIC
gh issue close 166 -c "Already fixed: 5 edge-case tests added (half-bits/nibble/non-hex/mismatch)" -R masa-57/NIC
gh issue close 167 -c "Already fixed: has_embedding=1 in workers + assertions use == 1" -R masa-57/NIC
gh issue close 169 -c "Already fixed: assertion verifying s3_key stays original on S3 move failure" -R masa-57/NIC
gh issue close 170 -c "Already fixed: 7 validation edge-case tests added" -R masa-57/NIC
gh issue close 163 -c "Already fixed: pagination + empty result tests for product-images endpoint" -R masa-57/NIC
```

**Step 2: Verify debt register CSV matches**

Ensure all 22 rows in `docs/audit/debt_register_148.csv` have `status` = `closed`.

**Step 3: Commit**

```bash
git add docs/audit/debt_register_148.csv
git commit -m "chore: close 22 already-fixed medium-priority issues

Closes #115, #122, #124, #128, #133, #135, #137, #138, #142, #143,
#148, #150, #152, #155, #157, #159, #163, #164, #166, #167, #169, #170"
```

---

## Track 1: Testing Improvements (5 issues)

### Task 1.1: Fix Overly Broad Mock (#160, M-T1)

**Problem:** `test_batch_embedding_failure_retries_per_image` mocks `_process_single_image` so broadly that the test doesn't verify actual retry behavior.

**Files:**
- Modify: `tests/unit/test_pipeline.py` — find test near line ~205-231
- Test: Same file

**Step 1: Read the current test to understand what's mocked**

```bash
grep -n "test_batch_embedding_failure" tests/unit/test_pipeline.py
```

Read the test and identify which mock is too broad.

**Step 2: Write a more targeted test**

Replace the overly-broad mock with specific mocks:
- Mock `compute_embeddings_batch` to raise on first call, succeed on second
- Keep `process_single_image` unmocked (or mock only its external dependencies like S3)
- Assert that the retry path is actually taken (verify `retry_single_image_ingest` is called)

**Step 3: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_pipeline.py -k "test_batch_embedding" -v
```

**Step 4: Commit**

```bash
git add tests/unit/test_pipeline.py
git commit -m "test: narrow mock scope in batch embedding retry test

Fixes #160"
```

### Task 1.2: Add Worker Entrypoint Tests (#165, M-T3)

**Problem:** No tests for `worker/entrypoint.py` argument parsing.

**Files:**
- Create: `tests/unit/test_entrypoint.py`
- Reference: `src/nic/worker/entrypoint.py` (46 lines, argparse-based CLI)

**Step 1: Write failing tests for entrypoint argument parsing**

```python
"""Tests for worker/entrypoint.py argument parsing."""

import pytest
from unittest.mock import patch, AsyncMock

# Test 1: Valid ingest command parses correctly
def test_ingest_command_calls_run_ingest():
    with patch("sys.argv", ["entrypoint", "ingest", "--image-id", "img-123"]), \
         patch("nic.worker.ingest.run_ingest", new_callable=AsyncMock) as mock_ingest, \
         patch("asyncio.run") as mock_run:
        from nic.worker.entrypoint import main
        main()
        mock_run.assert_called_once()

# Test 2: Valid cluster command parses correctly
def test_cluster_command_calls_run_cluster():
    with patch("sys.argv", ["entrypoint", "cluster", "--job-id", "job-456"]), \
         patch("nic.worker.cluster.run_full_clustering_job", new_callable=AsyncMock) as mock_cluster, \
         patch("asyncio.run") as mock_run:
        from nic.worker.entrypoint import main
        main()
        mock_run.assert_called_once()

# Test 3: Missing required args raises SystemExit
def test_missing_required_args_exits():
    with patch("sys.argv", ["entrypoint", "ingest"]):
        with pytest.raises(SystemExit):
            from nic.worker.entrypoint import main
            main()

# Test 4: Unknown command raises SystemExit
def test_unknown_command_exits():
    with patch("sys.argv", ["entrypoint", "unknown"]):
        with pytest.raises(SystemExit):
            from nic.worker.entrypoint import main
            main()
```

**Step 2: Run tests to verify they fail (module import issues)**

```bash
uv run pytest tests/unit/test_entrypoint.py -v
```

**Step 3: Adjust tests based on actual entrypoint structure, make them pass**

The entrypoint uses `argparse` with subparsers. Adjust mocks to match actual import paths.

**Step 4: Run tests to verify all pass**

```bash
uv run pytest tests/unit/test_entrypoint.py -v
```

**Step 5: Commit**

```bash
git add tests/unit/test_entrypoint.py
git commit -m "test: add worker entrypoint argument parsing tests

Fixes #165"
```

### Task 1.3: Add Clustering with Missing Embeddings Test (#168, M-T6)

**Problem:** No test for what happens when clustering pipeline encounters images without embeddings.

**Files:**
- Modify: `tests/unit/test_clustering.py` (or create if needed)
- Reference: `src/nic/services/clustering_pipeline.py`, `src/nic/services/clustering.py`

**Step 1: Write failing test**

Test that `cluster_level2` gracefully handles images where some have `has_embedding=0` / `embedding=None`:
- Mix of images with and without embeddings
- Verify only embedded images are clustered
- Verify non-embedded images are excluded (not crash)

```python
@pytest.mark.unit
def test_cluster_level2_skips_images_without_embeddings():
    """cluster_level2 should only process images that have embeddings."""
    import numpy as np
    # Create mix: 5 with embeddings, 3 without
    rng = np.random.default_rng(42)
    embeddings_with = [rng.standard_normal(768).astype(np.float32) for _ in range(5)]
    # Verify function filters correctly or raises appropriate error
    # (check actual function signature to determine expected behavior)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_clustering.py -k "missing_embeddings" -v
```

**Step 3: Implement fix if needed (or verify existing behavior is correct)**

**Step 4: Run tests**

```bash
uv run pytest tests/unit/test_clustering.py -v
```

**Step 5: Commit**

```bash
git add tests/unit/test_clustering.py
git commit -m "test: add clustering test with missing embeddings

Fixes #168"
```

### Task 1.4: Fix Integration Fixture Cleanup (#171, M-T9)

**Problem:** Integration fixture cleanup catches exceptions but doesn't re-raise, so cleanup failures are silently swallowed.

**Files:**
- Modify: `tests/integration/conftest.py:38-48`

**Step 1: Read current cleanup code**

Current pattern (lines 38-48):
```python
try:
    await session.rollback()
    await session.execute(text("TRUNCATE images, products, l1_groups, l2_clusters, jobs CASCADE"))
    await session.commit()
except Exception:
    logging.getLogger(__name__).error("Fixture cleanup failed — test data may leak", exc_info=True)
    try:
        await session.rollback()
    except Exception:
        logging.getLogger(__name__).error("Rollback after cleanup failure also failed", exc_info=True)
```

**Step 2: Add `raise` after logging to fail fast**

```python
try:
    await session.rollback()
    await session.execute(text("TRUNCATE images, products, l1_groups, l2_clusters, jobs CASCADE"))
    await session.commit()
except Exception:
    logging.getLogger(__name__).error("Fixture cleanup failed — test data may leak", exc_info=True)
    try:
        await session.rollback()
    except Exception:
        logging.getLogger(__name__).error("Rollback after cleanup failure also failed", exc_info=True)
    raise  # Fail fast — don't let corrupted state leak to next test
```

**Step 3: Run integration tests to verify no regressions**

```bash
uv run pytest tests/integration/ -v --timeout=60
```

(Integration tests require Docker/PostgreSQL — may skip if not available locally)

**Step 4: Commit**

```bash
git add tests/integration/conftest.py
git commit -m "test: fail fast on integration fixture cleanup errors

Fixes #171"
```

### Task 1.5: Add Migration Rollback Tests (#161, M-T10) — LARGE

**Problem:** No tests verify that Alembic migrations can be rolled back (downgrade).

**Files:**
- Create: `tests/integration/test_migrations.py`
- Reference: `src/nic/migrations/` (Alembic directory)

**Step 1: Write migration rollback test**

```python
"""Test that all Alembic migrations can upgrade and downgrade cleanly."""

import pytest
from alembic import command
from alembic.config import Config

@pytest.mark.integration
async def test_migrations_upgrade_and_downgrade(db_engine):
    """All migrations upgrade and downgrade without errors."""
    alembic_cfg = Config("alembic.ini")
    # Upgrade to head
    command.upgrade(alembic_cfg, "head")
    # Downgrade one step
    command.downgrade(alembic_cfg, "-1")
    # Re-upgrade to head
    command.upgrade(alembic_cfg, "head")
```

**Step 2: Run test**

```bash
uv run pytest tests/integration/test_migrations.py -v
```

**Step 3: Fix any downgrade issues found**

**Step 4: Commit**

```bash
git add tests/integration/test_migrations.py
git commit -m "test: add Alembic migration rollback scenario tests

Fixes #161"
```

### Task 1.6: Scaffold E2E Tests (#162, M-T11) — LARGE

**Problem:** Empty E2E tests directory — no end-to-end tests exist.

**Files:**
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_health_e2e.py`

**Step 1: Create E2E conftest with real HTTP client**

```python
"""E2E test fixtures — tests against a running API instance."""

import pytest
from httpx import AsyncClient

@pytest.fixture
async def e2e_client():
    """HTTP client targeting a running API (local or staging)."""
    import os
    base_url = os.environ.get("NIC_E2E_BASE_URL", "http://localhost:8000")
    async with AsyncClient(base_url=base_url) as client:
        yield client
```

**Step 2: Write minimal E2E health check test**

```python
"""E2E health check tests."""

import pytest

@pytest.mark.e2e
async def test_health_endpoint(e2e_client):
    resp = await e2e_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")

@pytest.mark.e2e
async def test_detailed_health_endpoint(e2e_client):
    resp = await e2e_client.get("/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert "database" in data
```

**Step 3: Run tests (requires running API)**

```bash
NIC_E2E_BASE_URL=http://localhost:8000 uv run pytest tests/e2e/ -v -m e2e
```

**Step 4: Commit**

```bash
git add tests/e2e/
git commit -m "test: scaffold E2E tests with health check smoke tests

Fixes #162"
```

---

## Track 2: Performance Optimizations (3 issues)

### Task 2.1: Verify UMAP Double-Run (#151, M-P1)

**Problem:** UMAP reportedly runs twice per clustering — once for 25D reduction, once for 2D visualization.

**Files:**
- Read: `src/nic/services/clustering.py:100-182`

**Step 1: Verify current state**

Read `clustering.py` and check if UMAP `fit_transform` is called once or twice. Based on agent analysis, this appears to already be fixed — UMAP runs once for 25D, then PCA projects from 25D to 2D.

**Step 2: If already fixed, close the issue**

```bash
gh issue close 151 -c "Verified: UMAP runs once for 25D reduction. PCA projects 25D→2D for visualization (no second UMAP call). See clustering.py:149-164." -R masa-57/NIC
```

**Step 3: Update debt register**

Set M-P1 status to `closed` in `docs/audit/debt_register_148.csv`.

**Step 4: If NOT fixed, implement the optimization**

Replace second UMAP call with PCA projection:
```python
from sklearn.decomposition import PCA
viz_coords = PCA(n_components=2).fit_transform(umap_25d)
```

**Step 5: Commit if changes made**

```bash
git add src/nic/services/clustering.py docs/audit/debt_register_148.csv
git commit -m "perf: verify UMAP single-run optimization

Fixes #151"
```

### Task 2.2: Make HNSW ef_search Configurable (#153, M-P3)

**Problem:** `ef_search=100` is hardcoded in `vector_store.py:26`. Should be configurable.

**Files:**
- Modify: `src/nic/config.py` — add `hnsw_ef_search: int = 100`
- Modify: `src/nic/services/vector_store.py:26` — use `settings.hnsw_ef_search`
- Create: `tests/unit/test_vector_store.py` (or add to existing)

**Step 1: Write failing test**

```python
@pytest.mark.unit
async def test_find_similar_uses_configured_ef_search():
    """find_similar_images should use settings.hnsw_ef_search."""
    # Mock settings to have custom ef_search value
    # Verify SET LOCAL ivfflat.probes or hnsw.ef_search uses that value
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_vector_store.py -k "ef_search" -v
```

**Step 3: Add config field**

In `src/nic/config.py`:
```python
hnsw_ef_search: int = 100
```

**Step 4: Use config in vector_store.py**

Replace hardcoded `100` with `settings.hnsw_ef_search`.

**Step 5: Run tests**

```bash
uv run pytest tests/unit/test_vector_store.py -v
```

**Step 6: Commit**

```bash
git add src/nic/config.py src/nic/services/vector_store.py tests/unit/test_vector_store.py
git commit -m "perf: make HNSW ef_search configurable via NIC_HNSW_EF_SEARCH

Fixes #153"
```

### Task 2.3: Reduce Image Opens During Ingest (#154, M-P4)

**Problem:** Image opened 3+ times per ingest (hashes, dimensions, thumbnail). Should be single-pass.

**Files:**
- Read: `src/nic/worker/pipeline_ingest.py` and `src/nic/worker/image_processing.py`
- Modify: `src/nic/worker/image_processing.py` — combine hash + dimensions into single PIL open

**Step 1: Trace the current image-open calls**

Read `image_processing.py` to identify where PIL opens occur:
- `compute_hashes(file_bytes)` → opens PIL Image
- `get_image_dimensions(file_bytes)` → opens PIL Image
- `generate_thumbnail(file_bytes)` → opens PIL Image

**Step 2: Write failing test**

```python
@pytest.mark.unit
def test_process_image_opens_pil_once():
    """Single PIL.Image.open per image during processing."""
    # Mock PIL.Image.open to count calls
    # Process one image through the full pipeline
    # Assert PIL.Image.open called exactly once
```

**Step 3: Implement single-pass processing**

Create a helper that opens the image once and extracts all needed data:
```python
def extract_image_metadata(file_bytes: bytes) -> ImageMetadata:
    """Single PIL open: compute hashes, dimensions, and thumbnail."""
    img = Image.open(io.BytesIO(file_bytes))
    phash = imagehash.phash(img)
    dhash = imagehash.dhash(img)
    width, height = img.size
    # Thumbnail also from same img object
    thumb_bytes = _generate_thumbnail_from_pil(img)
    return ImageMetadata(phash=str(phash), dhash=str(dhash), width=width, height=height, thumbnail=thumb_bytes)
```

**Step 4: Update callers to use the combined function**

**Step 5: Run all tests**

```bash
uv run pytest -m unit -v
```

**Step 6: Commit**

```bash
git add src/nic/worker/image_processing.py src/nic/services/image_store.py tests/
git commit -m "perf: single PIL open per image during ingest

Combines hash computation, dimension extraction, and thumbnail
generation into one function to avoid reopening the image 3+ times.

Fixes #154"
```

---

## Track 3: API Design Enhancements (9 issues)

### Task 3.1: Add HTTP Caching Headers (#114, M-API1)

**Files:**
- Modify: `src/nic/main.py` — add cache control middleware or per-endpoint headers
- Modify: `src/nic/api/images.py`, `src/nic/api/clusters.py`, `src/nic/api/products.py`
- Create/Modify: `tests/unit/test_api_endpoints.py`

**Step 1: Write failing test**

```python
@pytest.mark.unit
def test_get_images_has_cache_control_header(self, client, override_db):
    """GET /images should return Cache-Control header."""
    # Set up mock
    response = client.get("/api/v1/images")
    assert "cache-control" in response.headers
```

**Step 2: Run test to verify it fails**

**Step 3: Add Cache-Control headers to GET endpoints**

Strategy: Add a `CacheControlMiddleware` or use FastAPI `Response` parameter:

```python
@router.get("/images", response_model=ImageListOut)
async def list_images(
    response: Response,
    ...
):
    response.headers["Cache-Control"] = "private, max-age=30"
    # ... existing logic
```

- List endpoints: `Cache-Control: private, max-age=30`
- Single resource: `Cache-Control: private, max-age=60`
- Health: `Cache-Control: no-cache`
- File URLs: `Cache-Control: private, max-age=300` (presigned URLs valid 15 min)

**Step 4: Run tests**

**Step 5: Commit**

```bash
git commit -m "feat(api): add Cache-Control headers to GET endpoints

Fixes #114"
```

### Task 3.2: Add ETag Support (#119, M-API2)

**Files:**
- Modify: `src/nic/api/images.py`, `src/nic/api/products.py`
- Reference: `src/nic/models/db.py` (updated_at column)

**Step 1: Write failing test**

```python
def test_get_image_returns_etag(self, client, override_db):
    response = client.get("/api/v1/images/test-id")
    assert "etag" in response.headers
```

**Step 2: Implement ETag generation**

Use the `updated_at` timestamp + `id` to generate ETags:
```python
import hashlib
etag = hashlib.md5(f"{image.id}:{image.updated_at}".encode()).hexdigest()
response.headers["ETag"] = f'"{etag}"'
```

Handle `If-None-Match` header → return 304 Not Modified.

**Step 3: Run tests**

**Step 4: Commit**

```bash
git commit -m "feat(api): add ETag/conditional request support

Fixes #119"
```

### Task 3.3: Add Pagination Navigation Links (#120, M-API3)

**Files:**
- Modify: `src/nic/models/schemas.py` — add `links` field to list schemas
- Modify: All list endpoints in `src/nic/api/`

**Step 1: Write failing test**

```python
def test_list_images_includes_pagination_links(self, client, override_db):
    response = client.get("/api/v1/images?offset=10&limit=5")
    data = response.json()
    assert "links" in data
    assert "next" in data["links"]
    assert "prev" in data["links"]
```

**Step 2: Add PaginationLinks schema**

```python
class PaginationLinks(BaseModel):
    self_: str = Field(alias="self")
    next: str | None = None
    prev: str | None = None
    first: str
    last: str | None = None
```

**Step 3: Add `links` to all list response schemas**

Update `ImageListOut`, `L1GroupListOut`, `L2ClusterListOut`, `JobListOut`, `ProductListOut`, `CandidateListOut`.

**Step 4: Generate links in endpoints**

```python
def build_pagination_links(request: Request, total: int, offset: int, limit: int) -> PaginationLinks:
    base = str(request.url).split("?")[0]
    # ... compute next/prev/first/last
```

**Step 5: Run tests**

**Step 6: Commit**

```bash
git commit -m "feat(api): add pagination navigation links to list responses

Fixes #120"
```

### Task 3.4: Document Filter/Sort in OpenAPI (#126, M-API9)

**Files:**
- Modify: `src/nic/api/images.py`, `src/nic/api/clusters.py`, `src/nic/api/jobs.py`, `src/nic/api/products.py`

**Step 1: Add OpenAPI descriptions to query parameters**

```python
@router.get(
    "/images",
    response_model=ImageListOut,
    summary="List images",
    description="Returns paginated list of images. Supports filtering by embedding status and L1 group membership.",
)
async def list_images(
    l1_group_id: int | None = Query(None, description="Filter by L1 group ID"),
    has_embedding: bool | None = Query(None, description="Filter by embedding status (true/false)"),
    ...
):
```

Repeat for all list endpoints.

**Step 2: Run quality checks**

```bash
uv run ruff check src/ && uv run mypy src/nic/
```

**Step 3: Commit**

```bash
git commit -m "docs(api): add filter/sort parameter descriptions to OpenAPI

Fixes #126"
```

### Task 3.5: Add RFC 7807 Problem Detail (#116, M-API11)

**Files:**
- Modify: `src/nic/models/schemas.py` — add `ProblemDetail` model
- Modify: `src/nic/main.py` — update exception handlers

**Step 1: Write failing test**

```python
def test_error_response_follows_rfc7807(self, client, override_db):
    response = client.get("/api/v1/images/nonexistent")
    data = response.json()
    assert "type" in data
    assert "title" in data
    assert "status" in data
    assert "detail" in data
```

**Step 2: Create ProblemDetail schema**

```python
class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None
```

**Step 3: Update exception handlers in main.py**

```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ProblemDetail(
            title=http.HTTPStatus(exc.status_code).phrase,
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url),
            request_id=request.state.request_id if hasattr(request.state, "request_id") else None,
        ).model_dump(),
        headers=exc.headers,
    )
```

**Step 4: Run tests**

**Step 5: Commit**

```bash
git commit -m "feat(api): implement RFC 7807 problem detail error responses

Fixes #116"
```

### Task 3.6: Fix Cluster Hierarchy Pagination (#118, M-API13)

**Problem:** Unclustered groups ignore `offset` — only `limit` is applied.

**Files:**
- Modify: `src/nic/api/clusters.py:81-86` — add `.offset(pagination.offset)`
- Modify: `tests/unit/test_api_endpoints.py`

**Step 1: Write failing test**

```python
def test_cluster_hierarchy_unclustered_respects_offset(self, client, override_db):
    """GET /clusters with offset should skip unclustered groups too."""
    # Create mock data with >10 unclustered groups
    # Request with offset=5
    # Verify unclustered groups start from 6th item
```

**Step 2: Fix the bug**

In `src/nic/api/clusters.py`, line ~86, add `.offset(pagination.offset)`:

```python
unclustered_result = await db.execute(
    select(L1Group)
    .where(L1Group.l2_cluster_id.is_(None))
    .order_by(L1Group.member_count.desc())
    .offset(pagination.offset)  # ADD THIS
    .limit(pagination.limit)
)
```

**Step 3: Run tests**

**Step 4: Commit**

```bash
git commit -m "fix(api): apply offset to unclustered groups in cluster hierarchy

Fixes #118"
```

### Task 3.7: Add Presigned URL Expiry Field (#115 — already closed above)

Already handled in Track 0 (issue already fixed).

### Task 3.8: Offset-Based to Cursor-Based Pagination (#121, M-API4) — LARGE/DEFERRED

**Recommendation:** This is a large breaking change. Implement alongside M-API3 (pagination links) but as a separate PR. The current offset-based approach works for the ~10k image dataset. Consider deferring unless performance issues are observed at scale.

**If proceeding:** Add cursor-based pagination using `id` or `created_at` as cursor. Keep offset-based as fallback for backward compatibility.

**Minimal fix:** Add a note in OpenAPI docs about offset performance at high values and document the recommended pattern for clients.

```bash
gh issue comment 121 -b "Deferred: Current dataset (~10k images) doesn't exhibit offset pagination perf issues. Will implement cursor-based pagination when scale demands it. Pagination links (#120) provide the foundation." -R masa-57/NIC
```

### Task 3.9: Idempotency Key Support (#123, M-API6) — LARGE/DEFERRED

**Recommendation:** This requires significant infrastructure (idempotency key store, TTL, response caching). The current advisory lock prevents duplicate pipeline/cluster runs. Consider deferring.

```bash
gh issue comment 123 -b "Deferred: Advisory locks prevent duplicate job runs. Full idempotency key support requires response caching infrastructure — will implement when needed for external integrations beyond n8n." -R masa-57/NIC
```

### Task 3.10: Bulk Operations (#125, M-API8) — LARGE/DEFERRED

**Recommendation:** Bulk operations are not yet needed by the n8n integration workflow. Defer until a concrete use case emerges.

```bash
gh issue comment 125 -b "Deferred: No bulk operation requirements from current n8n integration. Will implement when a concrete use case emerges." -R masa-57/NIC
```

### Task 3.11: Job Completion Webhooks (#117, M-API12) — LARGE/DEFERRED

**Recommendation:** Manual polling works for n8n (which has built-in polling nodes). SSE or webhooks would be nice-to-have but not critical.

```bash
gh issue comment 117 -b "Deferred: n8n integration uses built-in polling. Webhook/SSE support would reduce latency but is not blocking any workflow." -R masa-57/NIC
```

---

## Track 4: Architecture & Code Quality (7 issues)

### Task 4.1: Refactor Modal Dispatch (#110, M-A4)

**Problem:** 4 nearly identical `submit_*_job` functions in `modal_dispatch.py`.

**Files:**
- Modify: `src/nic/services/modal_dispatch.py`
- Modify: `tests/unit/test_modal_dispatch.py` (if exists, or add tests)

**Step 1: Write test for generic dispatch**

```python
@pytest.mark.unit
async def test_submit_job_dispatches_to_correct_function():
    """submit_job should dispatch to the named Modal function."""
    with patch("nic.services.modal_dispatch._get_modal_function") as mock_get:
        mock_fn = MagicMock()
        mock_fn.spawn.return_value = MagicMock(object_id="call-123")
        mock_get.return_value = mock_fn
        result = await submit_job("run_ingest", "job-1", {"image_ids": ["a"]})
        assert result == "call-123"
```

**Step 2: Extract generic `_submit_job` helper**

```python
async def _submit_job(function_name: str, job_id: str, params: dict | None = None) -> str:
    fn = _get_modal_function(function_name)
    params_json = json.dumps(params) if params else None
    handle = fn.spawn(job_id, params_json)
    logger.info("Dispatched %s job_id=%s modal_call_id=%s", function_name, job_id, handle.object_id)
    return handle.object_id

@default_retry
async def submit_ingest_job(job_id: str, image_ids: list[str]) -> str:
    return await _submit_job("run_ingest", job_id, {"image_ids": image_ids})
# ... same pattern for other 3 functions
```

**Step 3: Run tests**

```bash
uv run pytest -m unit -v
```

**Step 4: Commit**

```bash
git commit -m "refactor: extract generic Modal dispatch helper

Reduces duplication across 4 submit_*_job functions.

Fixes #110"
```

### Task 4.2: Standardize DB Session Management (#111, M-A5)

**Problem:** API uses `Depends(get_db)`, workers use `async_session()` directly.

**Files:**
- Read: `src/nic/api/deps.py:20-22`, `src/nic/core/database.py:60`
- Modify: `src/nic/worker/helpers.py` — use same session factory pattern

**Step 1: Analyze current patterns**

API: `async def get_db(): async with async_session() as session: yield session`
Workers: `async with async_session() as session:` (direct usage)

Both use the same `async_session` factory — the pattern is actually consistent. The difference is just FastAPI DI vs direct context manager. This is by design (workers don't use FastAPI).

**Step 2: If already consistent, close the issue**

```bash
gh issue close 111 -c "Verified: Both API (via Depends(get_db)) and workers (via async_session() context manager) use the same session factory from core/database.py. The difference is intentional — workers don't run inside FastAPI." -R masa-57/NIC
```

**Step 3: Update debt register**

### Task 4.3: Extract Batch Operations Abstraction (#112, M-A6)

**Problem:** Concurrent download+error pattern repeated in pipeline and gdrive_sync.

**Files:**
- Read: `src/nic/worker/pipeline_discover.py:18-36`, `src/nic/worker/gdrive_download.py:24-66`

**Step 1: Analyze current patterns**

Both modules already have their own `download_and_dedup` / `download_s3_concurrent` functions that are well-structured. The GDrive download was already extracted to `gdrive_download.py` and pipeline to `pipeline_discover.py`.

**Step 2: If already refactored, close the issue**

```bash
gh issue close 112 -c "Already refactored: Pipeline downloads in pipeline_discover.py, GDrive downloads in gdrive_download.py. Both have dedicated download+dedup+error functions. Further abstraction would over-generalize two different source systems (S3 vs GDrive API)." -R masa-57/NIC
```

### Task 4.4: Refactor cluster_level2 Complexity (#132, M-CQ6)

**Problem:** `cluster_level2` is 88 lines with multiple responsibilities.

**Files:**
- Modify: `src/nic/services/clustering.py:100-182`
- Modify: `tests/unit/test_clustering.py`

**Step 1: Read function and identify extractable sections**

Likely sections:
1. Input validation + UMAP computation
2. HDBSCAN clustering
3. PCA visualization
4. Result assembly

**Step 2: Write tests for each extracted function**

```python
@pytest.mark.unit
def test_compute_umap_reduction():
    """UMAP reduces 768D to target dimensions."""

@pytest.mark.unit
def test_run_hdbscan_clustering():
    """HDBSCAN assigns cluster labels."""

@pytest.mark.unit
def test_compute_visualization_coords():
    """PCA projects to 2D for visualization."""
```

**Step 3: Extract helper functions**

```python
def _reduce_dimensions(embeddings: np.ndarray, n_components: int = 25) -> np.ndarray:
    """UMAP dimensionality reduction."""

def _cluster_embeddings(reduced: np.ndarray, min_cluster_size: int) -> np.ndarray:
    """HDBSCAN clustering on reduced embeddings."""

def _compute_viz_coords(reduced: np.ndarray) -> np.ndarray:
    """PCA projection to 2D for visualization."""
```

**Step 4: Run tests**

```bash
uv run pytest tests/unit/test_clustering.py -v
```

**Step 5: Commit**

```bash
git commit -m "refactor: extract helper functions from cluster_level2

Breaks 88-line function into focused helpers:
- _reduce_dimensions (UMAP)
- _cluster_embeddings (HDBSCAN)
- _compute_viz_coords (PCA)

Fixes #132"
```

### Task 4.5: Separate Worker Orchestration from Business Logic (#113, M-A7)

**Problem:** Workers mix job lifecycle management with domain logic.

**Files:**
- Read: `src/nic/worker/pipeline.py`, `src/nic/worker/cluster.py`, `src/nic/worker/gdrive_sync.py`

**Step 1: Analyze current state**

The workers already use `worker_lifecycle()` context manager (from `helpers.py`) which handles:
- Advisory lock acquisition
- Job status transitions (RUNNING → COMPLETED/FAILED)
- Error handling and rollback

The actual business logic is delegated to:
- `pipeline_discover.py`, `pipeline_ingest.py` (pipeline)
- `clustering_pipeline.py` (cluster)
- `gdrive_download.py` (gdrive)

**Step 2: If already well-separated, close**

```bash
gh issue close 113 -c "Already separated: worker_lifecycle() in helpers.py handles orchestration (locks, job status, error handling). Business logic lives in dedicated modules (pipeline_discover.py, pipeline_ingest.py, clustering_pipeline.py, gdrive_download.py). Workers are thin dispatchers." -R masa-57/NIC
```

### Task 4.6: Configuration Coupling (#108, M-A2) — LARGE/DEFERRED

**Problem:** `settings` imported directly in 18 modules.

**Recommendation:** This is a large refactoring effort (dependency injection across 18 modules) with minimal runtime benefit. The current pattern works and is standard for FastAPI apps. Defer.

```bash
gh issue comment 108 -b "Deferred: Direct settings import is the standard FastAPI/Pydantic pattern. Full DI refactoring would touch 18 modules with minimal runtime benefit. Consider when adding multi-tenant or test isolation requirements." -R masa-57/NIC
```

### Task 4.7: Service Layer Inconsistency (#109, M-A3) — LARGE/DEFERRED

**Problem:** Mix of functional/singleton/session-based service patterns.

**Recommendation:** The current patterns are appropriate for their domains (embedding is stateless/functional, image_store is a singleton, vector_store needs sessions). Standardizing would add unnecessary abstraction. Defer.

```bash
gh issue comment 109 -b "Deferred: Current service patterns match their domain needs — embedding.py is stateless (functional), image_store.py caches S3 client (singleton), vector_store.py needs DB sessions. Forcing uniform pattern would add unnecessary abstraction." -R masa-57/NIC
```

---

## Track 5: DevOps & Security (5 issues)

### Task 5.1: Add Secrets Rotation Documentation (#141, M-DO10)

**Files:**
- Create: `docs/runbooks/secrets-rotation.md`

**Step 1: Write secrets rotation runbook**

```markdown
# Secrets Rotation Runbook

## Inventory

| Secret | Location | Rotation Frequency |
|--------|----------|--------------------|
| NIC_API_KEY | Railway env, Modal `nic-env` | Quarterly |
| NIC_DATABASE_URL | Railway env, Modal `nic-env` | On compromise |
| NIC_S3_ACCESS_KEY_ID | Railway env, Modal `nic-env` | Quarterly |
| NIC_S3_SECRET_ACCESS_KEY | Railway env, Modal `nic-env` | Quarterly |
| NIC_GDRIVE_SERVICE_ACCOUNT_JSON | Modal `nic-env` | Annually |
| MODAL_TOKEN_ID / MODAL_TOKEN_SECRET | Railway env | Quarterly |
| NIC_SENTRY_DSN | Railway env | On compromise |

## Rotation Steps

### 1. API Key Rotation
1. Generate new key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update Railway: `railway variables set NIC_API_KEY=<new-key>`
3. Update Modal: `modal secret set nic-env NIC_API_KEY=<new-key>`
4. Update n8n HTTP credentials
5. Verify: `curl -H "X-API-Key: <new-key>" https://<api>/health`

### 2. Database URL Rotation
1. Rotate password in Neon dashboard
2. Update Railway + Modal with new connection string
3. Verify: Hit /health/detailed, check database connectivity

### 3. S3/R2 Credentials
1. Create new API token in Cloudflare R2
2. Update Railway + Modal
3. Verify: Trigger test ingest, check S3 operations succeed
4. Revoke old token
```

**Step 2: Commit**

```bash
git add docs/runbooks/secrets-rotation.md
git commit -m "docs: add secrets rotation runbook

Fixes #141"
```

### Task 5.2: Configure Railway Resource Limits (#147, M-DO6)

**Files:**
- Modify: `railway.json` (if Railway supports resource config via JSON)
- Alternative: Document recommended Railway dashboard settings

**Step 1: Check Railway resource configuration options**

Railway resource limits are typically set via the dashboard or `railway.toml`, not `railway.json`.

**Step 2: Add resource configuration documentation**

Add to `docs/runbooks/` or update `railway.json`:

```json
{
  "build": {
    "dockerfilePath": "Dockerfile.railway"
  },
  "deploy": {
    "healthcheckPath": "/health",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

**Step 3: Document recommended Railway dashboard settings**

```markdown
## Railway Resource Configuration

Recommended settings (configure via Railway dashboard):
- Memory: 512 MB (API-only, no ML deps)
- CPU: 0.5 vCPU
- Replicas: 1 (stateful advisory lock)
- Region: Same as Neon DB
```

**Step 4: Commit**

```bash
git add railway.json docs/
git commit -m "ops: configure Railway resource limits and restart policy

Fixes #147"
```

### Task 5.3: Pin Modal Dependencies (#144, M-DO3)

**Problem:** Modal dependencies use only `>=` bounds, risking version drift.

**Files:**
- Modify: `src/nic/modal_app.py:10-31`

**Step 1: Read current dependency definitions**

Check the Modal image `pip_install` calls for dependency specs.

**Step 2: Add upper bounds**

Replace `>=` with `>=X.Y,<X+1.0` (compatible release bounds):

```python
# Before:
.pip_install("sqlalchemy>=2.0", "asyncpg>=0.29")
# After:
.pip_install("sqlalchemy>=2.0,<3.0", "asyncpg>=0.29,<1.0")
```

Use `~=` (compatible release) or `>=,<` for each dependency.

**Step 3: Run mypy and tests**

```bash
uv run mypy src/nic/ && uv run pytest -m unit -v
```

**Step 4: Commit**

```bash
git add src/nic/modal_app.py
git commit -m "ops: add upper bounds to Modal dependencies

Prevents breaking changes from major version bumps.

Fixes #144"
```

### Task 5.4: Add Coverage Report Merging (#140, M-DO1)

**Files:**
- Modify: `.github/workflows/ci-cd.yml`

**Step 1: Add coverage artifact upload in both unit and integration jobs**

Both jobs already upload coverage artifacts. Need to add a merge step.

**Step 2: Add coverage merge job**

```yaml
  coverage-report:
    needs: [unit-test, integration-test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: coverage-*
          merge-multiple: true
      - name: Merge coverage reports
        run: |
          pip install coverage
          coverage combine
          coverage report --fail-under=70
          coverage xml -o combined-coverage.xml
      - uses: actions/upload-artifact@v4
        with:
          name: combined-coverage
          path: combined-coverage.xml
```

**Step 3: Run CI to verify**

Push branch and check CI output.

**Step 4: Commit**

```bash
git add .github/workflows/ci-cd.yml
git commit -m "ci: merge unit and integration coverage reports

Adds a coverage-report job that combines both reports for a
unified coverage view.

Fixes #140"
```

### Task 5.5: Validate GDrive Service Account JSON (#158, M-S2)

**Problem:** GDrive service account JSON stored as raw env var string — error-prone.

**Files:**
- Modify: `src/nic/config.py` — add validator for `gdrive_service_account_json`
- Add test: `tests/unit/test_config.py`

**Step 1: Write failing test**

```python
@pytest.mark.unit
def test_config_validates_gdrive_json_format():
    """Config should validate that GDrive JSON is parseable."""
    import json
    # Valid JSON: should not raise
    valid = json.dumps({"type": "service_account", "project_id": "test"})
    # Invalid JSON: should raise or warn
```

**Step 2: Add model_validator**

```python
@model_validator(mode="after")
def validate_gdrive_json(self) -> "Settings":
    if self.gdrive_service_account_json:
        try:
            data = json.loads(self.gdrive_service_account_json)
            if not isinstance(data, dict) or "type" not in data:
                raise ValueError("GDrive JSON must contain 'type' field")
        except json.JSONDecodeError as e:
            raise ValueError(f"NIC_GDRIVE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}") from e
    return self
```

**Step 3: Run tests**

```bash
uv run pytest tests/unit/test_config.py -v
```

**Step 4: Commit**

```bash
git add src/nic/config.py tests/unit/test_config.py
git commit -m "security: validate GDrive service account JSON at startup

Catches malformed JSON early instead of at runtime.

Fixes #158"
```

---

## Execution Summary

### Phase 1: Track 0 (Close 22 fixed issues)
- Batch `gh issue close` commands
- Update debt register CSV
- ~5 minutes, no code changes

### Phase 2: Tracks 1-5 in Parallel

| Track | Tasks | New Issues | Deferred |
|-------|-------|------------|----------|
| 1: Testing | 6 tasks | 5 implemented | 0 |
| 2: Performance | 3 tasks | 1-2 implemented, 1 verify+close | 0 |
| 3: API Design | 11 tasks | 5 implemented | 4 deferred |
| 4: Architecture | 7 tasks | 2 implemented, 3 verify+close | 2 deferred |
| 5: DevOps/Security | 5 tasks | 5 implemented | 0 |

### Phase 3: Quality Gate

After all tracks complete:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy src/nic/
uv run pytest -m unit
python3 scripts/debt_sync.py validate --strict
```

### Deferred Issues (comment but don't close)

These 6 issues are large-effort, low-impact for the current ~10k image dataset:
- #121 (M-API4): Cursor-based pagination
- #123 (M-API6): Idempotency keys
- #125 (M-API8): Bulk operations
- #117 (M-API12): Job webhooks/SSE
- #108 (M-A2): Configuration decoupling
- #109 (M-A3): Service layer standardization

### Issues That May Already Be Fixed (verify during implementation)

- #151 (M-P1): UMAP double-run — agent analysis suggests already fixed
- #111 (M-A5): DB session inconsistency — appears consistent by design
- #112 (M-A6): Batch operations abstraction — already extracted to separate modules
- #113 (M-A7): Worker orchestration separation — already using worker_lifecycle()
