# Technical Debt

Last updated: 2026-02-18 (post-closure update)

## Summary

**Audit Wave 5** (2026-02-18): Multi-agent comprehensive review with 9 specialized agents (security, code quality, performance, test quality, architecture, database, API design, backend logic, DevOps).

**Total Issues Found**: 105 | **Cross-agent consensus items**: 7 | **Quick Wins**: ~9

| Severity | Found | Quick Wins | Deferred |
|----------|-------|------------|----------|
| Critical | 4     | 1          | 3        |
| High     | 14    | 6          | 8        |
| Medium   | 38    | 3          | 35       |
| Low      | 49    | 0          | 49       |

Note: the table above is the initial audit snapshot. See the resolution update below for current closure status.

## Wave 5 Resolution Update (2026-02-18)

Closed on GitHub:
- **C1** — [#227](https://github.com/masa-57/NIC/issues/227)
- **C2** — [#228](https://github.com/masa-57/NIC/issues/228)
- **C3** — [#229](https://github.com/masa-57/NIC/issues/229)
- **C4** — [#230](https://github.com/masa-57/NIC/issues/230)
- **H-S1** — [#231](https://github.com/masa-57/NIC/issues/231)
- **H-S2** — [#232](https://github.com/masa-57/NIC/issues/232)
- **H-P1** — [#233](https://github.com/masa-57/NIC/issues/233)
- **M-P1 (promoted to high in issue tracking)** — [#234](https://github.com/masa-57/NIC/issues/234)
- **H-P3** — [#235](https://github.com/masa-57/NIC/issues/235)
- **H-B1** — [#236](https://github.com/masa-57/NIC/issues/236)
- **H-API1** — [#238](https://github.com/masa-57/NIC/issues/238)

## Critical Issues

### C1: Clustering destroys all L1/L2 data without transaction safety ✅ Resolved ([#227](https://github.com/masa-57/NIC/issues/227))
- **File**: `src/nic/services/clustering_pipeline.py:61-96`
- **Agent**: backend-specialist, database-specialist, performance-engineer
- **Impact**: Bulk DELETE of all L1 groups and L2 clusters before re-creation. Crash mid-way leaves zero clustering data. No SAVEPOINTs.
- **Fix**: Wrap in transaction with savepoints, or adopt write-new-swap-pointers strategy
- **Effort**: medium

### C2: O(n²) cosine distance matrix in L1 clustering ✅ Resolved ([#228](https://github.com/masa-57/NIC/issues/228))
- **File**: `src/nic/services/clustering.py`
- **Agent**: performance-engineer
- **Impact**: `scipy.spatial.distance.squareform(cdist(...))` creates ~800MB matrix at 5k images. OOM on Railway 512MB limit.
- **Fix**: Replace with pairwise threshold-based approach or use HDBSCAN's native distance computation
- **Effort**: medium

### C3: HNSW index rebuild locks table (migration 015) ✅ Resolved ([#229](https://github.com/masa-57/NIC/issues/229))
- **File**: `src/nic/migrations/versions/015_tune_hnsw_index_params.py:25-29`
- **Agent**: database-specialist
- **Impact**: `CREATE INDEX` without `CONCURRENTLY` takes ACCESS EXCLUSIVE lock, blocking all reads/writes during rebuild.
- **Fix**: Use `CREATE INDEX CONCURRENTLY` with AUTOCOMMIT isolation. Same issue in migration 003.
- **Effort**: medium

### C4: SET LOCAL statement_timeout reset after commit ⚡ Quick Win ✅ Resolved ([#230](https://github.com/masa-57/NIC/issues/230))
- **File**: `src/nic/worker/helpers.py:197`
- **Agent**: database-specialist, backend-specialist, performance-engineer
- **Impact**: Timeout applied before `mark_job_running()` which commits, resetting the timeout. Workers run without protection.
- **Fix**: Change `SET LOCAL` to `SET` (session-level) or move after commit
- **Effort**: small

## High-Priority Issues

### Security
- **H-S1**: API key exposed in URL query parameter (`api/clusters.py:267`) — browser history, proxy logs, Referer headers. Fix: use session tokens. Effort: medium. ✅ Resolved ([#231](https://github.com/masa-57/NIC/issues/231))
- **H-S2**: No Pillow decompression bomb protection (`image_store.py:111`, `embedding.py:59`) — 20MB PNG → billions of pixels → OOM. Fix: set `MAX_IMAGE_PIXELS`. Effort: small ⚡. ✅ Resolved ([#232](https://github.com/masa-57/NIC/issues/232))

### Performance
- **H-P1**: N+1 embedding load in product endpoints (`api/products.py:215-241`) — `db.refresh(product, ["images"])` loads 768-dim vectors just to count. Fix: use COUNT query. Effort: small ⚡. ✅ Resolved ([#233](https://github.com/masa-57/NIC/issues/233))
- **H-P2**: Serial blocking S3 moves in discovery (`pipeline_discover.py`) — 20k+ blocking boto3 calls serially. Fix: use `asyncio.gather`. Effort: small ⚡
- **H-P3**: Connection pool under-sized (`core/database.py`) — `pool_size=5 + max_overflow=10` insufficient. Fix: increase defaults. Effort: small ⚡. ✅ Resolved ([#235](https://github.com/masa-57/NIC/issues/235))
- **H-P4**: Float64 intermediate allocation in embedding load — 91MB when 30MB (float32) suffices. Effort: small ⚡
- **H-P5**: Visualization loads ALL images into memory (`cluster_visualization.py:42-55`) — 10k images + 20k serial presigned URL calls. Fix: add pagination/limit. Effort: medium

### Backend Logic
- **H-B1**: GDrive cron spawns worker without checking existing running jobs (`modal_app.py:105-129`) — wastes GPU cold starts on advisory lock failures. Fix: pre-check PENDING/RUNNING jobs. Effort: small ⚡. ✅ Resolved ([#236](https://github.com/masa-57/NIC/issues/236))

### Architecture
- **H-A1**: API layer contains 50+ direct `db.execute()` calls — missing service layer for CRUD reads (`api/clusters.py`, `products.py`, `images.py`). Effort: medium

### API Design
- **H-API1**: ErrorDetail vs ProblemDetail mismatch — OpenAPI spec declares `ErrorDetail`, actual responses use `ProblemDetail`. Effort: small ⚡. ✅ Resolved ([#238](https://github.com/masa-57/NIC/issues/238))
- **H-API2**: DELETE product doesn't clearly handle image orphaning (`api/products.py:245-256`). Effort: small

### DevOps
- **H-DO1**: No `permissions` block on CI workflows (`ci-cd.yml`, `deploy-staging.yml`) — overly broad token permissions. Effort: small ⚡. ✅ Resolved ([#237](https://github.com/masa-57/NIC/issues/237))
- **H-DO2**: Dockerfile uses unpinned `uv:latest` (`Dockerfile:4`) — breaking UV change silently breaks builds. Effort: small ⚡. ✅ Resolved ([#237](https://github.com/masa-57/NIC/issues/237))
- **H-DO3**: No rollback mechanism for Modal deployments — broken deploy shows green CI. Effort: medium. ✅ Resolved ([#237](https://github.com/masa-57/NIC/issues/237))

### Testing
- **H-T1**: 5 modules with zero test coverage — cluster_visualization (148 LOC), rate_limit, metrics, image_processing (146 LOC), modal_app. Effort: medium. ✅ Resolved ([#239](https://github.com/masa-57/NIC/issues/239))

## Medium-Severity Issues

### Performance (8 medium)
- **M-P1**: Presigned URL cache has no TTL — serves expired URLs (flagged by 4 agents!) (`image_store.py:170-187`). Effort: small ⚡. ✅ Resolved ([#234](https://github.com/masa-57/NIC/issues/234))
- **M-P2**: Parallel count+data queries could cut list endpoint latency ~40% (`api/images.py`, `clusters.py`). Effort: small
- **M-P3**: get_hierarchy issues 5-6 sequential DB queries (all independent) (`api/clusters.py:85-116`). Effort: small
- **M-P4**: find_similar_images issues 2 sequential round-trips (`vector_store.py:30-48`). Effort: small
- **M-P5**: create_and_dispatch_job has 3 unnecessary round-trips (`api/deps.py:52-84`). Effort: small
- **M-P6**: GDrive download lacks concurrency semaphore — Google API rate limiting (`gdrive_download.py:33-42`). Effort: small
- **M-P7**: Missing index on `images.created_at` for ORDER BY (`api/images.py:41`). Effort: small
- **M-P8**: Missing `gc.collect()` after GPU sub-batch processing (`embedding.py:111-113`). Effort: small

### Security (4 medium)
- **M-S1**: f-string SQL interpolation in `SET LOCAL` statements (`vector_store.py:27`, `helpers.py:197`). Effort: small
- **M-S2**: OpenAPI docs (Swagger/redoc) exposed in production (`main.py:51-56`). Effort: small
- **M-S3**: Browser router bypasses API key dependency (`api/router.py:23-24`). Effort: small. ✅ Resolved ([#231](https://github.com/masa-57/NIC/issues/231))
- **M-S4**: No rate limiting on visualization endpoint (`api/clusters.py:260-275`). Effort: small

### Code Quality (9 medium)
- **M-CQ1**: ETag middleware reads entire response into memory with O(n²) concat (`main.py:208-244`). Effort: small
- **M-CQ2**: `cluster_level2` returns `dict[str, object]` — forces 5+ `type: ignore` (`clustering.py:140`). Effort: small ⚡
- **M-CQ3**: Duplicate auth logic in `clusters.py` vs `core/auth.py` (`clusters.py:252-257`). Effort: small
- **M-CQ4**: Hardcoded rate limits "30/minute" on search endpoints — not configurable (`search.py:27`). Effort: small
- **M-CQ5**: No json.loads error handling for params_json in 3 workers (`pipeline.py:27`, `cluster.py:15`, `gdrive_sync.py:27`). Effort: small
- **M-CQ6**: `cluster_level2` uses falsy `or` instead of `is not None` — inconsistent with L1 (`clustering.py:150-151`). Effort: small
- **M-CQ7**: Duplicate param extraction in clusters.py and pipeline.py (`clusters.py:56-67`, `pipeline.py:37-49`). Effort: small
- **M-CQ8**: Sensitive info in GDrive error logs — `logger.exception` may leak JSON fragments (`gdrive.py:34-35`). Effort: small
- **M-CQ9**: sync_database_url fragile string replacement (`config.py:131-133`). Effort: small

### Architecture (5 medium)
- **M-A1**: main.py overloaded at 384 lines (middleware + handlers + health) — extract to separate modules. Effort: medium
- **M-A2**: Prometheus metrics defined but never instrumented — dead code (`core/metrics.py`). Effort: small ⚡
- **M-A3**: main.py imports from worker layer — conceptual layer violation (`main.py:29`). Effort: small
- **M-A4**: api/deps.py contains job orchestration business logic (`deps.py:45-84`). Effort: small
- **M-A5**: S3 client is synchronous in async app — inconsistent wrapping (`image_store.py:57-73`). Effort: medium

### Database (5 medium)
- **M-D1**: Missing index on `jobs.completed_at` for health check query (`main.py:363-367`). Effort: small
- **M-D2**: Unbounded IN clause in pipeline S3 key dedup (`pipeline_discover.py:56`). Effort: small
- **M-D3**: Advisory lock uses session-level (not transaction-level) — crash leaves lock held until pool_recycle. Effort: small (doc)
- **M-D4**: Missing `pool_timeout` configuration (`core/database.py:50-58`). Effort: small. ✅ Resolved ([#235](https://github.com/masa-57/NIC/issues/235))
- **M-D5**: Full-table UPDATE+DELETE in clustering pipeline in single transaction (`clustering_pipeline.py:61-62`). Effort: large

### API Design (5 medium)
- **M-API1**: 413 error returns plain JSON, not RFC 7807 ProblemDetail (`main.py:129-133`). Effort: small
- **M-API2**: Visualization endpoint lacks pagination (`api/clusters.py:226-249`). Effort: medium
- **M-API3**: Hierarchy pagination shares offset/limit across two independent sets (`api/clusters.py:80-128`). Effort: medium
- **M-API4**: PATCH product cannot clear nullable fields (`api/products.py:220-242`). Effort: small
- **M-API5**: Rate limits missing on product CRUD endpoints (`api/products.py`). Effort: small

### Backend Logic (2 medium)
- **M-B1**: worker_lifecycle marks job failed on dead session after rollback failure (`helpers.py:200-210`). Effort: small
- **M-B2**: Pipeline ingest: S3 ops succeed but DB commit can fail → orphaned files (`pipeline_ingest.py:89-104`). Effort: medium

### DevOps (4 medium)
- **M-DO1**: Smoke test `continue-on-error: true` swallows deploy failures (`ci-cd.yml:171`). Effort: small
- **M-DO2**: Staging workflow skips integration tests and container scan (`deploy-staging.yml:37`). Effort: medium
- **M-DO3**: Lint/test jobs duplicated across ci-cd.yml and deploy-staging.yml. Effort: medium
- **M-DO4**: Trivy action pinned to tag not SHA (`ci-cd.yml:49`). Effort: medium

### Testing (4 medium)
- **M-T1**: Duplicate auth tests across `test_pipeline.py` and `test_auth.py`. Effort: small. ✅ Resolved (de-duplicated in unit tests)
- **M-T2**: Duplicate `sweep_stale_jobs` tests in `test_worker_helpers.py` and `test_helpers.py`. Effort: small. ✅ Resolved (consolidated into `test_helpers.py`)
- **M-T3**: Integration test embeddings are all scalar multiples — cosine similarity always 1.0. Effort: small
- **M-T4**: Pipeline assertions don't verify call arguments (only `.assert_awaited_once()`). Effort: small

## Low-Severity Issues (~49 items)

### Security (11 low)
- Health check leaks DB state, presigned URL cache indefinite, image_id not UUID-validated, MD5 for ETag, error messages leak internal state, no content-type validation on images, S3 client cached indefinitely, GDrive credentials not using SecretStr, safe_filename minimal sanitization, request body accumulation memory, CSP img-src from dynamic config

### Code Quality (19 low)
- Naming inconsistencies, missing docstrings, magic numbers (JPEG quality 85, health threshold 5, timeout 1800s), dead re-export of hex_to_bitstring, unused `get_all_embeddings`, asyncio.to_thread overhead on cache hits, cluster_visualization HTML string concat, mixed _local_id pattern, missing logging context in workers

### Architecture (5 low)
- L2Cluster.centroid_image_id lacks FK constraint, worker entrypoint.py references abandoned AWS Batch, GDrive download recomputes content hash twice, inconsistent vector_store abstraction, missing error handling for `check_modal_job_status` successful return

### Database (5 low)
- Missing `images.created_at` index, no pool_timeout config, Modal N+1 status checks, missing FK centroid_image_id, double refresh in update_product

### API Design (10 low)
- POST search not deprecated, missing OpenAPI descriptions, inconsistent threshold validation (ge=0 vs ge=1), no DELETE/cancel for images/jobs, global error schemas missing from OpenAPI, pagination links relative not absolute, optional clustering body defaults undocumented, browser_router auth bypass undocumented

### DevOps (11 low)
- Missing timeout-minutes on jobs, staging missing pip-audit, bare pip install in smoke test, Docker build lacks cache, coverage-report runs on double failure, Dockerfile missing UV_COMPILE_BYTECODE, Dockerfile shorter start-period, Trivy missing SARIF upload, smoke test accepts 401, no CODEOWNERS file, branch protection unverified

### Testing (5 low)
- Unit tests use sync TestClient for async endpoints, vector_store over-mocked, test naming inconsistency, hardcoded 768 embedding dimension

### Documentation
- `docs/operations/log-aggregation.md` contains **inaccurate Railway log drain instructions** (lines 88-101) — Railway does NOT support log drains. Needs correction.

## Previously Fixed (Waves 1-4)

### Wave 4 (2026-02-15): Comprehensive multi-agent review
All 148 issues from Wave 4 cataloged. Quick wins applied for Dockerfile healthcheck, composite indexes, HTTP headers, visualization fixes, memory optimization, GDrive cache safety.

### Waves 1-3 (2026-02-11 to 2026-02-15)
All 38 issues from the initial audit resolved. See git history for details.

## Open Considerations

- [#23](https://github.com/masa-57/NIC/issues/23): Evaluate replacing `slowapi` with a maintained alternative
- [#29](https://github.com/masa-57/NIC/issues/29): GDrive sync duplicates ingest/pipeline logic
- Log visibility brainstorm paused — proposed "Lean Observability" approach (GH Actions health check + Sentry context + fix inaccurate docs)
