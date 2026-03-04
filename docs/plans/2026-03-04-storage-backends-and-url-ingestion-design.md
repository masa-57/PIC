# Design: Configurable Storage Backends & URL-Based Image Ingestion

**Date:** 2026-03-04
**Status:** Approved

## Overview

Two related features that expand PIC's image sourcing capabilities:

1. **Configurable Storage Backends** — Abstract storage behind a protocol so PIC can use S3-compatible (existing), Google Cloud Storage, or local filesystem.
2. **URL-Based Image Ingestion** — Accept image URLs via API. PIC downloads, deduplicates, and stores them using the configured backend.

## StorageBackend Protocol

A unified interface replacing direct S3 calls:

```python
@runtime_checkable
class StorageBackend(Protocol):
    def upload(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None: ...
    def download(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def move(self, source_key: str, dest_key: str) -> None: ...
    def list_objects(self, prefix: str) -> list[str]: ...
    def get_url(self, key: str, expires_in: int = 900) -> str: ...
    def exists(self, key: str) -> bool: ...
```

### Implementations

- **S3StorageBackend** — Refactored from current `image_store.py`. Works with AWS S3, Cloudflare R2, MinIO.
- **GCSStorageBackend** — Uses `google-cloud-storage` SDK. Presigned URLs via `generate_signed_url()`.
- **LocalStorageBackend** — Filesystem storage. `get_url()` returns path-based URLs served by a FastAPI static route mounted only when `storage_backend=local`.

### Factory

```python
@functools.lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    match settings.storage_backend:
        case "s3": return S3StorageBackend(...)
        case "gcs": return GCSStorageBackend(...)
        case "local": return LocalStorageBackend(...)
```

Existing public functions (`upload_to_s3`, `download_from_s3`, etc.) become thin wrappers delegating to the backend for backward compatibility. Helpers like `generate_thumbnail()`, `get_image_dimensions()`, and the presigned URL cache remain in `image_store.py`.

## Configuration

New settings in `config.py` (all prefixed `PIC_`):

```python
# Backend selection
storage_backend: str = "s3"  # "s3" | "gcs" | "local"

# GCS (required when storage_backend=gcs)
gcs_bucket: str = ""
gcs_project_id: str = ""
gcs_credentials_json: str = ""  # Service account JSON

# Local (required when storage_backend=local)
local_storage_path: Path = Path("data/storage")
local_storage_base_url: str = ""  # e.g., http://localhost:8000/files
```

### Validation

- `storage_backend` must be `s3`, `gcs`, or `local`
- `gcs`: requires `gcs_bucket` and `gcs_credentials_json`
- `s3`: existing validation unchanged
- `local`: path must exist or be creatable; blocked in production (`env=production`)
- Default is `s3` — existing deployments work without changes

## URL-Based Image Ingestion

### Endpoint

```
POST /api/v1/images/ingest
```

### Request

```python
class UrlIngestRequest(BaseModel):
    urls: list[HttpUrl]  # 1-100 URLs
    auto_pipeline: bool = False  # Trigger clustering after ingest
```

### Response

```python
class UrlIngestOut(BaseModel):
    job_id: str
    urls_submitted: int
```

### Flow

1. API validates URLs (count, http/https scheme only)
2. Creates Job record (`JobType.URL_INGEST`)
3. Dispatches to Modal worker
4. Worker downloads each URL via `httpx`:
   - Size limit: `max_image_download_mb` (reused)
   - Timeout: 30s per URL
   - Content-Type must be `image/*`
   - Concurrent downloads with semaphore (`max_concurrent_downloads`)
5. Per image: compute content hash, deduplicate, upload to storage backend under `images/` prefix, create Image record
6. If `auto_pipeline=true`, trigger existing pipeline (Phase 1 + 2)

### Job Result Format

```json
{
    "total": 10,
    "succeeded": 7,
    "duplicates": 2,
    "failed": 1,
    "errors": [{"url": "https://...", "reason": "Timeout after 3 retries"}]
}
```

### Data Model Change

New nullable column on Image: `source_url: str | None` (original URL if ingested via URL endpoint).

Rate limiting: same as pipeline (`job_trigger_rate_limit: 5/minute`).

## File Structure

### New Files

```
src/pic/services/storage/
    __init__.py          # Re-exports get_storage_backend, StorageBackend
    base.py              # StorageBackend protocol
    s3.py                # S3StorageBackend
    gcs.py               # GCSStorageBackend
    local.py             # LocalStorageBackend

src/pic/worker/
    url_ingest.py        # URL download + ingest worker

tests/unit/
    test_storage_s3.py
    test_storage_gcs.py
    test_storage_local.py
    test_url_ingest.py

tests/integration/
    test_images_url_ingest.py
```

### Modified Files

- `config.py` — new settings
- `image_store.py` — delegates to storage backend, keeps helpers
- `constants.py` — `_validate_s3_key` renamed to `_validate_storage_key`
- `models/db.py` — `source_url` column on Image
- `models/schemas.py` — new request/response schemas, `ImageOut` updated
- `pipeline_discover.py` — use storage backend instead of direct S3 calls
- `pipeline_ingest.py` — same
- `worker/ingest.py` — same
- `modal_app.py` — same
- `api/router.py` — register new endpoint
- `api/images.py` — add ingest endpoint

### New Dependency

`google-cloud-storage` — optional, only imported when `gcs` backend selected.

## Error Handling

### URL Ingestion

- Invalid URL scheme — 422 at validation
- Non-image content-type — skipped, logged in job result
- Timeout/connection failure — retried 3x, then skipped with error logged
- Oversized image — skipped, logged
- All URLs fail — job COMPLETED (not FAILED) with per-URL status

### Storage Backends

- Credential failures — fail fast at startup via Settings validation
- Local filesystem permission errors — fail fast at startup
- Transient errors — all backends use tenacity retry (3 attempts, exponential backoff)
- Backend mismatch (DB has keys from different backend) — not handled automatically; documented as migration concern

### Local Backend

- `get_url()` returns path-based URL (e.g., `/files/processed/abc.jpg`)
- Static file route mounted only when `storage_backend=local`
- Storage key validation (`_validate_storage_key`) prevents path traversal across all backends
