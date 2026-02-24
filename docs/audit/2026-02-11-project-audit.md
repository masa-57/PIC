# NIC Project Audit Report

**Date**: 2026-02-11
**Scope**: Code quality, test coverage, API design, error handling, security, observability, performance, developer experience

---

## Executive Summary

The NIC project is a well-structured hierarchical image clustering API with clean module separation, good dependency management, and modern deployment infrastructure (Railway + Modal + R2 + Neon). However, the audit identified **10 critical issues**, **18 important issues**, and **20 suggestions** across all dimensions.

**Top priorities:**
1. Apply authentication to all write endpoints (only `/pipeline/run` is protected)
2. Fix SSL certificate verification disabled on database connections
3. Fix O(n^2) nested loop in clustering phase (blocks scaling to 10k images)
4. Increase test coverage from 31% to 70%+ (API layer is at 0%)
5. Add structured logging and request tracing

---

## 1. Code Quality & Structure

### What's Good
- Clean module separation: `api/`, `services/`, `worker/`, `models/`, `core/`
- Proper FastAPI dependency injection with `Depends()`
- Pydantic Settings for config with `NIC_` prefix and `extra: "ignore"`
- Stateless service functions with clear I/O boundaries
- Eager loading with `selectinload()` prevents N+1 in API layer

### Critical

| # | Issue | Location |
|---|-------|----------|
| 1 | **Race condition in cluster clear+recreate**: Between clearing all L1 groups and recreating them, queries could find orphaned images. Needs transaction isolation. | `worker/cluster.py:105-125`, `worker/pipeline.py:311-328` |
| 2 | **Major code duplication**: `cluster.py` and `pipeline.py` both implement the full L1+L2 clustering pipeline with advisory locks, progress tracking, and group assignment. | `worker/cluster.py:94-167` vs `worker/pipeline.py:299-399` |

### Important

| # | Issue | Location |
|---|-------|----------|
| 3 | `has_embedding` typed as `Mapped[bool]` but stored as `Integer(0/1)`. Confusing; forces `= 0`/`= 1` in raw SQL. | `models/db.py:39` |
| 4 | Missing type annotations on `db` parameter (suppressed with `# noqa: ANN001`). | `worker/ingest.py:49`, `worker/cluster.py:67`, `worker/pipeline.py:81,120,190,282` |
| 5 | S3 client created fresh on every call. Should cache/reuse. | `services/image_store.py:12-19` |
| 6 | Global mutable state for DINOv2 model (`_model = None`). Thread-unsafe (low risk in Modal but not obvious). | `services/embedding.py:14-15` |
| 7 | Excessive per-image DB commits in clustering loops. With 10k images = 10k commits. Should batch. | `worker/cluster.py:105-126`, `worker/pipeline.py:310-328` |

---

## 2. Test Coverage

### What's Good
- 43 unit tests, all passing
- Core algorithms well-tested (clustering, hashing, L1 grouping)
- Auth module at 100% coverage
- Good test markers (`unit`, `integration`, `e2e`)

### Overall: 31% coverage — HIGH RISK

| Layer | Coverage | Notes |
|-------|----------|-------|
| API endpoints | **0%** | All 15 endpoints completely untested |
| Worker tasks | **22%** | `cluster.py` at 0%, `pipeline.py` at 26% |
| Services | **41%** | DINOv2 inference untested, Modal dispatch at 0%, vector store at 0% |
| Core | **69%** | Auth 100%, DB 92% |
| Models | **97%** | Schema definitions compile |
| Config | **96%** | Only `sync_database_url` untested |

### Critical Gaps

| # | Missing Tests | Impact |
|---|---------------|--------|
| 8 | All API endpoints (clusters, images, search, jobs, pipeline) — 0% | User-facing contract completely unvalidated |
| 9 | `worker/cluster.py` — 0% (203 lines) | Clustering job failures hidden until production |
| 10 | `services/modal_dispatch.py` — 0% | Job dispatch reliability unknown |
| 11 | `services/vector_store.py` — 0% | Semantic search feature untested |
| 12 | `services/embedding.py` model inference (lines 56-100) — 0% | DINOv2 loading, device selection, batch processing untested |
| 13 | `pipeline.py` batch ingest phase (lines 190-279) — 0% | 189 lines of ingest logic untested |
| 14 | No integration tests at all (testcontainers, real DB, real S3) | Component interactions unvalidated |

---

## 3. API Design & Error Handling

### What's Good
- Consistent pagination on list endpoints (`offset`/`limit` with `ge=1, le=200`)
- Proper HTTP semantics (POST for mutations, GET for queries)
- Descriptive HTTPException messages
- API versioning via `/api/v1/` prefix

### Important

| # | Issue | Location |
|---|-------|----------|
| 15 | No bounds validation on clustering parameters (`l1_threshold`, `l2_min_cluster_size`). Accepts any value. | `api/clusters.py:29-55`, `api/pipeline.py:19-46` |
| 16 | `/clusters` hierarchy endpoint loads ALL clusters without pagination. Massive response at scale. | `api/clusters.py:63` |
| 17 | Bare `except Exception:` throughout workers. Too broad, swallows unexpected errors. | `worker/ingest.py:61`, `worker/pipeline.py:137,216,226,256,260` |
| 18 | No global exception handler for consistent error response format. | `main.py` |

---

## 4. Security

### Critical

| # | Issue | Location |
|---|-------|----------|
| 19 | **SSL certificate verification disabled** on DB connections. `check_hostname=False` + `CERT_NONE` makes SSL useless against MITM. | `core/database.py:18-22` |
| 20 | **Auth only on `/pipeline/run`**. All other endpoints (clusters/run, search, images, jobs) are completely unauthenticated. Anyone can trigger clustering jobs or access all images. | `api/pipeline.py:19` is the only endpoint using `verify_api_key` |
| 21 | **Health check leaks error details**: `f"error: {e}"` exposes connection strings, DB internals to public endpoint. | `main.py:41-43` |

### Important

| # | Issue | Location |
|---|-------|----------|
| 22 | API key auth defaults to disabled (empty string). Could accidentally deploy without auth. | `core/auth.py:11-16`, `config.py` `api_key: str = ""` |
| 23 | No image size/format validation. PIL opens anything; enables DoS via huge/malformed images. | `services/embedding.py:50,62,87`, `services/image_store.py:54,66` |
| 24 | Presigned URLs expire in 1 hour — long-lived for potentially sensitive images. | `services/image_store.py:101-107` |
| 25 | `ingest.py` doesn't compute `content_hash`, so duplicates bypass detection. | `worker/ingest.py:20-45` |
| 26 | No CORS configuration. If browser clients are intended, cross-origin requests will fail. | `main.py` (no middleware) |
| 27 | No rate limiting on any endpoint. Search endpoints do full table scans. | All API endpoints |
| 28 | Docker containers run as root. | `Dockerfile`, `Dockerfile.railway` |

---

## 5. Observability

### Critical

| # | Issue | Location |
|---|-------|----------|
| 29 | **No structured logging**. Basic `logging.basicConfig()` with string format. Cannot correlate logs across Railway API and Modal workers. No request IDs. | `core/logging.py:1-14` |

### Important

| # | Issue | Location |
|---|-------|----------|
| 30 | No request/response middleware (latency, status codes, error tracking). | `main.py` |
| 31 | No metrics collection (Prometheus/StatsD). Cannot monitor request counts, embedding latencies, queue depths. | Entire codebase |
| 32 | Logging level hardcoded to INFO. Not configurable via env var. | `core/logging.py:5-10` |
| 33 | No audit logging for sensitive operations (job triggers, search queries, auth failures). | All endpoints |

---

## 6. Performance

### Critical

| # | Issue | Location |
|---|-------|----------|
| 34 | **O(n^2) nested loop** in L2 cluster assignment. For each cluster member, iterates ALL `db_groups`. With 1000 groups = 1M+ iterations. Should use dict lookup. | `worker/cluster.py:169-172`, `worker/pipeline.py:365-369` |
| 35 | **Full table scan for duplicate search**: Loads ALL images with phashes, computes Hamming distance in Python. O(n) per search at 10k images. | `api/search.py:63-66` |
| 36 | **Blocking S3 operations in async context**: Synchronous boto3 calls block the event loop. No timeouts, no retries. | `worker/pipeline.py:136`, all S3 calls |

### Important

| # | Issue | Location |
|---|-------|----------|
| 37 | Missing indexes on `Image.l1_group_id` and `L1Group.l2_cluster_id`. Full table scans for filtering. | `models/db.py:43,57` |
| 38 | Missing index on `Image.has_embedding`. Used in API filter queries. | `models/db.py:39` |
| 39 | N+1 delete pattern: Loops `db.delete(g)` for each group instead of bulk `DELETE FROM`. | `worker/cluster.py:104-108` |
| 40 | Connection pool too small (5 + 10 overflow) for concurrent Modal workers + API. | `core/database.py:32-38` |
| 41 | UMAP `n_neighbors=30` is fixed. Crashes if `n_neighbors > n_groups - 1` at certain scales. | `config.py:27-28` |
| 42 | All embeddings loaded into memory for clustering (768-dim x 10k = ~60MB + O(n^2) UMAP distance matrices). | `worker/cluster.py:69-90` |

---

## 7. Developer Experience

### What's Good
- Excellent documentation (README.md, CLAUDE.md with gotchas)
- Clean `.env.example` with all variables
- ML dependencies properly separated (`[ml]` extra)
- Good CI/CD pipeline (lint -> test -> deploy)
- Multi-stage Dockerfiles
- Alembic migrations set up
- Useful scripts (`seed.py`, `retry.py`, `visualize.py`)

### Important

| # | Issue | Location |
|---|-------|----------|
| 43 | No migration documentation in README (how to run/generate). | `README.md` |
| 44 | No `Makefile` or `justfile` for common commands (10+ distinct commands documented). | Project root |
| 45 | No integration tests in CI (only unit tests run). | `.github/workflows/ci-cd.yml:30` |
| 46 | No security scanning in CI (`pip-audit`, `bandit`, `trivy`). | `.github/workflows/ci-cd.yml` |
| 47 | No coverage threshold enforcement in CI. | `.github/workflows/ci-cd.yml` |

### Suggestions

| # | Issue | Location |
|---|-------|----------|
| 48 | Add pre-commit hooks for secret detection. | Project root |
| 49 | Add volume mounts to docker-compose.yml for hot reload. | `docker-compose.yml:19-30` |
| 50 | Add `USER` directive to Dockerfiles (run as non-root). | `Dockerfile`, `Dockerfile.railway` |

---

## Prioritized Action Plan

### Phase 1: Security (Do Immediately)

1. **Apply auth to all write endpoints** — Add `Depends(verify_api_key)` to `POST /clusters/run`, search endpoints, etc.
2. **Fix SSL verification** — Remove `check_hostname=False` and `CERT_NONE` in `database.py`
3. **Sanitize health check errors** — Return `"error"` not `f"error: {e}"`
4. **Add image size/format validation** — Reject files > 50MB or non-image formats

### Phase 2: Performance (Do Before 10k Images)

5. **Fix O(n^2) cluster assignment** — Use `{g.id: g for g in db_groups}` dict lookup
6. **Fix duplicate search** — Use DB-level Hamming distance or BK-tree index
7. **Add missing DB indexes** — `l1_group_id`, `l2_cluster_id`, `has_embedding`
8. **Batch DB commits** — Commit every 100-1000 items, not per-image
9. **Bulk delete** — Replace loop `db.delete(g)` with single `DELETE FROM`

### Phase 3: Test Coverage (Target 70%)

10. **Add API endpoint tests** — FastAPI TestClient for all 15 endpoints
11. **Add worker integration tests** — Test clustering pipeline with sample data
12. **Add Modal dispatch tests** — Mock `modal.Function` calls
13. **Add vector store tests** — Test pgvector queries
14. **Add embedding model tests** — Mock DINOv2, test batch processing

### Phase 4: Observability

15. **Add structured JSON logging** — With request IDs for cross-service tracing
16. **Add request/response middleware** — Log method, path, status, latency
17. **Make log level configurable** — `NIC_LOG_LEVEL` env var
18. **Add health check for downstream deps** — Modal, S3, pgvector

### Phase 5: Code Quality

19. **Extract shared clustering logic** — Deduplicate `cluster.py` and `pipeline.py`
20. **Add transaction isolation** — Wrap cluster clear+recreate in serializable transaction
21. **Cache S3 client** — Module-level lazy init like DINOv2 model
22. **Add proper type annotations** — Remove `# noqa: ANN001` suppressions
23. **Add parameter validation** — Bounds on clustering params in Pydantic schemas

### Phase 6: Developer Experience

24. **Add Makefile** — `make test`, `make lint`, `make local`, `make deploy`
25. **Document migrations** — Add run/generate commands to README
26. **Add security scanning to CI** — `pip-audit` step
27. **Add coverage threshold** — `pytest --cov-fail-under=70`
28. **Add pre-commit hooks** — Secret detection, lint

---

## Metrics Summary

| Metric | Current | Target |
|--------|---------|--------|
| Test coverage | 31% | 70%+ |
| API endpoint coverage | 0% (0/15) | 100% |
| Critical security issues | 3 | 0 |
| Missing DB indexes | 3 | 0 |
| Structured logging | No | Yes |
| Auth-protected endpoints | 1/15 | All write endpoints |
| CI security scanning | No | Yes |

---

*This audit was generated by analyzing all source files under `src/nic/`, `tests/`, configuration files, CI/CD pipelines, Docker files, and deployment configuration.*
