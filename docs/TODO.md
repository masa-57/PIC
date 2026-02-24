# NIC — Remaining Improvements

Tracked from comprehensive project review (2026-02-12). Items are grouped by effort.
See full review context in `.claude/plans/precious-skipping-nova.md`.

## Completed

- [x] #1 — Rate limiting enforcement (`@limiter.limit()` on endpoints)
- [x] #2 — Security headers middleware + tightened CORS
- [x] #3 — Clustering pipeline transaction atomicity (flush instead of mid-commit)
- [x] #5 — S3 retry logic (tenacity `@retry` on all S3 operations)
- [x] #6 — `/metrics` endpoint gated behind API key auth
- [x] #7 — Sentry auto-discovery integrations (removed empty `integrations=[]`)
- [x] #8 — S3 credential validation at startup (`@model_validator`)
- [x] #9 — Health check detail endpoint sanitized (no raw exception strings)
- [x] #10 — S3 move-before-DB-update ordering (already correct in code)
- [x] #11 — Job timeout sweeper (`sweep_stale_jobs` in `/health/detailed`)
- [x] #12 — Defensive dedup (`INSERT ... ON CONFLICT DO NOTHING`)
- [x] #13 — `_process_single_image` return value (correct — processing succeeds regardless of move)
- [x] #16 — Dead `mock_batch` fixture removed
- [x] #18 — Database indexes on `representative_image_id` columns + Alembic migration
- [x] #21 — Consistent `get_or_404()` usage in products.py
- [x] #22 — Consistent job result format in cluster worker

## Remaining — Medium Effort

- [ ] #4 — **Partial pipeline failure recovery**: Track per-image ingest status; add recovery/retry for partially-failed batches. Currently if Phase 1 fails after 50% of images, partial data persists with no way to re-ingest just the failures.
  - File: `src/nic/worker/pipeline.py`

- [ ] #19 — **Embedding batch size configurable**: `batch_size = 8` is hardcoded in pipeline worker. Add `NIC_EMBEDDING_BATCH_SIZE` to settings.
  - File: `src/nic/worker/pipeline.py`, `src/nic/config.py`

- [ ] #20 — **Pagination max offset guard**: `offset` param has no upper bound. Large offsets on small tables are wasteful. Add a max or switch to cursor-based pagination.
  - File: `src/nic/api/deps.py`

- [ ] #23 — **slowapi is unmaintained**: Last release ~2023. Consider switching to `fastapi-limiter` or custom middleware.
  - File: `pyproject.toml`

## Remaining — Larger Effort

- [ ] #14 — **Tests for untested modules**: `worker/entrypoint.py` (~45 lines), `core/database.py` (~40 lines), `modal_app.py` (~70 lines), `models/schemas.py` (~200 lines — Pydantic validation rules).

- [ ] #15 — **Concurrency and advisory lock tests**: Rate limiting verification, advisory lock contention under concurrent requests, two clustering jobs racing. Currently only single-lock failure is tested.

- [ ] #17 — **Reduce over-mocking in unit tests**: API endpoint tests mock the entire DB layer. Real query bugs (missing `selectinload`, wrong filters) won't be caught. Lean more on integration tests for API endpoints; keep unit tests for pure business logic.

## Audit Round 2 (2026-02-12) — Deferred Items

### Medium Effort

- [ ] #24 — **N+1 query in cluster hierarchy**: `GET /api/v1/clusters/hierarchy` eagerly loads all L2 clusters → L1 groups → images without pagination. Add offset/limit or lazy-load groups.
  - File: `src/nic/api/clusters.py`

- [ ] #25 — **Consistent error response format**: Not all error paths return `{"detail": ..., "request_id": ...}`. Wrap FastAPI's `HTTPException` handler to always include `request_id` from middleware.
  - Files: `src/nic/main.py`, `src/nic/models/schemas.py`

- [ ] #26 — **Tests for `sweep_stale_jobs`**: The stale job sweeper has no dedicated test coverage. Add unit tests for edge cases (no stale jobs, multiple stale jobs, already-failed jobs).
  - File: `tests/unit/test_core.py` or new `tests/unit/test_sweep_stale_jobs.py`

- [ ] #27 — **OpenAPI schema completeness**: Add `responses={404: {"model": ErrorDetail}, 409: ...}` to all endpoint decorators so generated API docs show error shapes.
  - Files: `src/nic/api/images.py`, `src/nic/api/clusters.py`, `src/nic/api/products.py`

- [ ] #28 — **Alembic migration for `l2_cluster_id` index**: Model now has `index=True` on `l1_groups.l2_cluster_id` but no migration was generated. Run `uv run alembic revision --autogenerate -m "Add index to l1_groups.l2_cluster_id"`.
  - File: `src/nic/models/db.py`

### Larger Effort

- [ ] #29 — **Modal health monitoring**: Add webhook/callback for Modal function failures so the API can proactively detect worker issues instead of waiting for job timeout sweeps.
  - Files: `src/nic/modal_app.py`, `src/nic/worker/helpers.py`

- [ ] #30 — **Database connection pool tuning**: Default pool settings may not be optimal under load. Requires load testing to determine `pool_size`, `max_overflow`, `pool_timeout` values.
  - File: `src/nic/core/database.py`

- [ ] #31 — **Upgrade Pillow to 12.1.1**: CVE-2026-25990 affects Pillow 12.1.0. Update in `pyproject.toml` and run `uv lock`.
  - File: `pyproject.toml`
