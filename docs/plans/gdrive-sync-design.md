# Plan: Google Drive → R2 Automatic Sync (2-Tier Modal)

## Context

The current n8n batch upload workflow (15 nodes, polling loops, credential management) is too complex to maintain and fragile for large batches (500+ files). The user needs a simpler, more reliable solution that:
- Handles 500+ files per batch
- Works across all platforms (users just drop files into Google Drive)
- Requires zero user interaction after one-time folder share
- Is easy to maintain (one Python file vs 15-node n8n workflow)
- Has optimal data movement (no unnecessary round-trips)
- Doesn't waste GPU money checking for files that may not exist

**Solution**: A 2-tier Modal architecture:
- **Tier 1** (CPU, every 15 min): Lightweight cron checks if new files exist in Google Drive. Cost: ~$0.001/run.
- **Tier 2** (T4 GPU, on-demand): Only spawned when files are found. Downloads, processes (hashes + embeddings + thumbnails) in memory, uploads to R2 `processed/`, clusters.

Files are **processed directly in memory** — they never pass through R2 `images/` prefix, eliminating the download-upload-redownload cycle. `/pipeline/run` remains unchanged for other use cases.

## Data Flow

```
Modal cron (CPU, every 15 min):
  check_gdrive_for_new_files
    → List Google Drive folder
    → If new files found: spawn GPU worker
    → If no files: return immediately (~2s)
         ↓ (only when files exist)
Modal GPU worker (T4, on-demand):
  sync_gdrive_to_r2
    For each batch of 8 images:
      1. Download from Google Drive → memory
      2. SHA256 dedup (check DB content_hash unique index)
      3. Compute DINOv2 embeddings (GPU batch)
      4. Compute pHash + dHash
      5. Generate thumbnail, get dimensions
      6. Upload original → R2 processed/{filename}
      7. Upload thumbnail → R2 thumbnails/{id}.jpg
      8. Create full DB record (metadata + embedding)
      9. Move file to processed/ subfolder in Google Drive
    After all batches:
      10. Run L1 + L2 clustering (reuse run_full_clustering)
```

One `GDRIVE_SYNC` job tracks the full process.

## Files to Create

### 1. `src/nic/services/gdrive.py` — Google Drive API wrapper

All GDrive operations encapsulated here.

**Functions:**
- `build_drive_service(service_account_json: str) -> Resource` — Init client from JSON string via `google.oauth2.service_account.Credentials.from_service_account_info(json.loads(...))`
- `list_image_files(service: Resource, folder_id: str) -> list[GDriveFile]` — Recursively list image files, **excluding** any subfolder named `processed`. Filter by `_IMAGE_EXTENSIONS`. Handle pagination (`nextPageToken`).
- `download_file(service: Resource, file_id: str) -> bytes` — Download file content via `files().get_media()`
- `get_or_create_processed_folder(service: Resource, parent_folder_id: str) -> str` — Find or create `processed` subfolder. Cache the result.
- `move_file_to_folder(service: Resource, file_id: str, current_parent_id: str, target_folder_id: str) -> None` — Move file by updating parents.

**Dataclass:**
```python
@dataclass
class GDriveFile:
    id: str
    name: str
    mime_type: str
    size: int
    parent_id: str  # Immediate parent folder ID (for move operation)
```

Use `tenacity` retry (3 attempts, exponential backoff) on all API calls. Scopes: `["https://www.googleapis.com/auth/drive"]` (read + write for move).

### 2. `src/nic/worker/gdrive_sync.py` — GPU sync + process worker

Follows the advisory lock pattern from [pipeline.py](src/nic/worker/pipeline.py). Processes images **inline** — no separate pipeline dispatch.

```python
_GDRIVE_SYNC_LOCK_ID = 0x4E494301  # Same as pipeline — both do clustering, must be mutually exclusive

async def run_gdrive_sync(job_id: str, params_json: str | None = None) -> None:
    params = json.loads(params_json) if params_json else {}
    async with async_session() as db:
        if not await acquire_advisory_lock(db, _GDRIVE_SYNC_LOCK_ID, job_id):
            return
        try:
            await db.execute(text("SET LOCAL statement_timeout = '3600s'"))
            await mark_job_running(db, job_id)
            await _sync_process_and_cluster(db, job_id, params)
        except Exception as e:
            await db.rollback()
            await mark_job_failed(db, job_id, str(e))
            raise
        finally:
            await release_advisory_lock(db, _GDRIVE_SYNC_LOCK_ID)
```

**`_sync_process_and_cluster(db, job_id, params)` logic:**

**Phase 1 — Download, dedup, process (progress 0.0 → 0.8):**
1. Build GDrive service from `settings.gdrive_service_account_json`
2. `list_image_files(service, settings.gdrive_folder_id)` — recursive, filtered
3. If no files: mark complete with empty stats, return early (no clustering)
4. `get_or_create_processed_folder(service, settings.gdrive_folder_id)`
5. Process in batches of 8 (same as pipeline, caps memory ~160MB):
   - For each file in batch:
     - Download from GDrive, validate size (`max_image_download_mb`)
     - Compute SHA256, check DB for duplicate (`content_hash` unique index)
     - If duplicate: move to `processed/` in GDrive, skip
   - For non-duplicate files in batch:
     - `compute_embeddings_batch()` — GPU batch (reuse from [embedding.py](src/nic/services/embedding.py))
     - For each: `compute_hashes()`, `generate_thumbnail()`, `get_image_dimensions()` (reuse from [embedding.py](src/nic/services/embedding.py) and [image_store.py](src/nic/services/image_store.py))
     - `upload_to_s3(image_bytes, f"processed/{filename}")` — original goes directly to R2 `processed/`
     - `upload_to_s3(thumb_bytes, f"thumbnails/{image_id}.jpg")` — thumbnail
     - Create DB `Image` record with full metadata (embedding, hashes, dimensions, `s3_key="processed/..."`, `has_embedding=True`)
     - `move_file_to_folder()` — move to `processed/` in GDrive
   - Update job progress

**Phase 2 — Clustering (progress 0.8 → 1.0):**
6. `run_full_clustering(db, params)` — reuse from [clustering_pipeline.py](src/nic/services/clustering_pipeline.py)
7. Mark job completed with summary

**Result JSON:**
```json
{
  "files_discovered": 50,
  "files_uploaded": 45,
  "duplicates_skipped": 2,
  "files_errored": 3,
  "total_bytes": 125000000,
  "l1_groups": 30,
  "l2_clusters": 8,
  "l2_noise_groups": 5,
  "total_images": 245
}
```

**Error handling:** Individual file failures logged and counted, don't abort sync. Only unrecoverable errors (bad credentials, folder not found) abort.

### 3. `src/nic/api/gdrive.py` — Manual trigger endpoint

```python
router = APIRouter(prefix="/gdrive", tags=["gdrive"])

@router.post("/sync", response_model=JobOut, status_code=202)
@limiter.limit("3/hour")
async def trigger_gdrive_sync(request, db) -> JobOut:
    if not settings.gdrive_folder_id:
        raise HTTPException(503, "Google Drive sync not configured")
    job = await create_and_dispatch_job(db, JobType.GDRIVE_SYNC, submit_gdrive_sync_job, None)
    return JobOut.model_validate(job)
```

Uses existing `create_and_dispatch_job()` from [deps.py](src/nic/api/deps.py). Keep `/pipeline/run` unchanged.

### 4. `tests/unit/test_gdrive_service.py`

Mock `googleapiclient.discovery.build()`. Tests:
- `test_list_image_files_recursive` — handles nested folders
- `test_list_image_files_excludes_processed` — skips processed/ subfolder
- `test_list_image_files_filters_extensions` — only image files
- `test_list_image_files_pagination` — handles nextPageToken
- `test_download_file_success`
- `test_move_file_to_folder`
- `test_get_or_create_processed_folder_creates_new`
- `test_get_or_create_processed_folder_returns_existing`

### 5. `tests/unit/test_gdrive_sync_worker.py`

Mock GDrive service + image_store + embedding. Tests:
- `test_sync_full_flow` — download, process, upload, cluster
- `test_sync_no_files_completes_without_clustering`
- `test_sync_acquires_advisory_lock`
- `test_sync_concurrent_lock_fails`
- `test_sync_skips_oversized_files`
- `test_sync_skips_duplicate_content_hash`
- `test_sync_continues_on_individual_failure`
- `test_sync_marks_job_completed_with_stats`

### 6. `tests/unit/test_gdrive_api.py`

- `test_trigger_sync_returns_202`
- `test_trigger_sync_not_configured_returns_503`

### 7. Alembic migration `009_add_gdrive_sync_job_type.py`

```python
revision = "..."
down_revision = "b3c4d5e6f7a8"

def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'GDRIVE_SYNC'")

def downgrade() -> None:
    pass  # Cannot remove enum values in PostgreSQL
```

## Files to Modify

### 1. `src/nic/models/db.py` — Add JobType enum value

Add at [line 25](src/nic/models/db.py#L25):
```python
GDRIVE_SYNC = "gdrive_sync"
```

### 2. `src/nic/config.py` — Add GDrive settings

Add after [line 44](src/nic/config.py#L44) (after `sentry_dsn`):
```python
# Google Drive Sync (optional — empty = disabled)
gdrive_service_account_json: str = ""  # Service account JSON credentials as string
gdrive_folder_id: str = ""             # Shared folder ID to sync from
```

### 3. `src/nic/modal_app.py` — 2-tier Modal functions

**Add Google deps to existing `nic_image`** (after `"tenacity>=8.0"` on [line 20](src/nic/modal_app.py#L20)):
```python
"google-api-python-client>=2.0",
"google-auth>=2.0",
```

**Add lightweight check image** (after `nic_image` definition, ~line 30):
```python
# Lightweight image for GDrive file check (no ML deps — fast cold start ~5s)
nic_check_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "pydantic-settings>=2.0",
        "google-api-python-client>=2.0",
        "google-auth>=2.0",
        "tenacity>=8.0",
    )
    .add_local_python_source("nic")
)
```

**Add Tier 1: CPU checker with cron** (after existing functions):
```python
@app.function(
    image=nic_check_image,
    schedule=modal.Cron("*/15 * * * *"),  # Every 15 minutes
    timeout=120,  # 2 min max
    concurrency_limit=1,
    secrets=[modal.Secret.from_name("nic-env")],
)
async def check_gdrive_for_new_files() -> None:
    """Lightweight check: list GDrive folder, spawn GPU worker if files found."""
    from nic.config import settings

    if not settings.gdrive_folder_id or not settings.gdrive_service_account_json:
        return

    from nic.services.gdrive import build_drive_service, list_image_files

    service = build_drive_service(settings.gdrive_service_account_json)
    files = list_image_files(service, settings.gdrive_folder_id)

    if not files:
        return  # Nothing to do — cost: ~2s CPU

    import logging
    logger = logging.getLogger(__name__)
    logger.info("Found %d new files in Google Drive, spawning GPU worker", len(files))

    # Spawn GPU worker (it creates its own Job record)
    fn = modal.Function.from_name("nic", "sync_gdrive_to_r2")
    fn.spawn()  # No args — worker reads config and creates job
```

**Add Tier 2: GPU processor (no schedule)** :
```python
@app.function(
    image=nic_image,
    gpu="T4",
    timeout=3600,
    concurrency_limit=1,
    secrets=[modal.Secret.from_name("nic-env")],
)
async def sync_gdrive_to_r2(job_id: str | None = None, params_json: str | None = None) -> None:
    """GPU worker: download from GDrive, process, upload to R2, cluster."""
    from nic.config import settings

    if not settings.gdrive_folder_id or not settings.gdrive_service_account_json:
        return

    import uuid
    from nic.core.database import async_session
    from nic.models.db import Job, JobStatus, JobType

    if job_id is None:
        job_id = str(uuid.uuid4())
        async with async_session() as db:
            db.add(Job(id=job_id, type=JobType.GDRIVE_SYNC, status=JobStatus.PENDING))
            await db.commit()

    from nic.worker.gdrive_sync import run_gdrive_sync as _run
    await _run(job_id, params_json)
```

### 4. `src/nic/services/modal_dispatch.py` — Add dispatch function

Add after [line 45](src/nic/services/modal_dispatch.py#L45):
```python
@_retry
async def submit_gdrive_sync_job(job_id: str, params: dict[str, int] | None = None) -> str:
    fn = modal.Function.from_name("nic", "sync_gdrive_to_r2")
    params_json = json.dumps(params) if params else None
    call = fn.spawn(job_id, params_json)
    logger.info("Spawned Modal GDrive sync %s (NIC job %s)", call.object_id, job_id)
    return call.object_id
```

### 5. `src/nic/api/router.py` — Register GDrive router

Add import + registration:
```python
from nic.api.gdrive import router as gdrive_router
api_router.include_router(gdrive_router)
```

### 6. `pyproject.toml` — Add Google dependencies

Add to `dependencies`:
```toml
"google-api-python-client>=2.0",
"google-auth>=2.0",
```

### 7. `.env.example` — Add GDrive env vars

Add after line 34:
```bash
# Google Drive Sync (optional — empty = disabled)
NIC_GDRIVE_SERVICE_ACCOUNT_JSON=  # Service account JSON as string (not a file path)
NIC_GDRIVE_FOLDER_ID=             # Folder ID from URL: drive.google.com/drive/folders/{THIS_PART}
```

## Reused Existing Code

| Function | From | Used For |
|---|---|---|
| `compute_embeddings_batch()` | [embedding.py](src/nic/services/embedding.py) | DINOv2 GPU batch embeddings |
| `compute_hashes()` | [embedding.py](src/nic/services/embedding.py) | pHash + dHash |
| `upload_to_s3()` | [image_store.py](src/nic/services/image_store.py) | Upload to R2 (original + thumbnail) |
| `generate_thumbnail()` | [image_store.py](src/nic/services/image_store.py) | JPEG thumbnail generation |
| `get_image_dimensions()` | [image_store.py](src/nic/services/image_store.py) | Width/height extraction |
| `run_full_clustering()` | [clustering_pipeline.py](src/nic/services/clustering_pipeline.py) | L1 + L2 clustering |
| `acquire/release_advisory_lock()` | [helpers.py](src/nic/worker/helpers.py) | Prevent concurrent syncs |
| `mark_job_running/failed/completed()` | [helpers.py](src/nic/worker/helpers.py) | Job lifecycle |
| `create_and_dispatch_job()` | [deps.py](src/nic/api/deps.py) | API endpoint job creation |
| `_IMAGE_EXTENSIONS` | [pipeline.py](src/nic/worker/pipeline.py) | Image extension filter (extract to shared constant) |

## Implementation Order

0. **Save plan**: Copy this plan to `docs/plans/gdrive-sync-design.md`
1. **Dependencies**: `pyproject.toml` + `uv sync`
2. **Config**: `config.py` + `.env.example`
3. **DB**: `db.py` enum + Alembic migration
4. **Service**: `services/gdrive.py` + unit tests
5. **Worker**: `worker/gdrive_sync.py` + unit tests
6. **Modal**: `modal_app.py` (2 images + 2 functions)
7. **Dispatch**: `modal_dispatch.py`
8. **API**: `api/gdrive.py` + `router.py` + unit tests
9. **Quality gates**: ruff + mypy + pytest + pip-audit

## Verification

1. `uv run ruff check src/ tests/ scripts/` — zero errors
2. `uv run ruff format --check src/ tests/ scripts/` — zero formatting issues
3. `uv run mypy src/nic/ --ignore-missing-imports` — zero type errors
4. `uv run pytest -m unit` — all tests pass
5. `uv run pip-audit` — no vulnerabilities
6. Manual test: set GDrive env vars, run `modal run src/nic/modal_app.py::sync_gdrive_to_r2`

## Notes

- **2-tier cost efficiency**: CPU checker runs 96x/day at ~$0.001 each = ~$0.10/day. GPU worker only runs when files exist. Vs. single GPU cron at ~$0.05/run × 4x/day = ~$0.20/day even with no files.
- **Advisory lock `0x4E494301`** — shared with pipeline. Both GDrive sync and pipeline run `run_full_clustering()` which does `DELETE + recreate` of all L1/L2 groups. Concurrent execution would cause data corruption. A 409 is returned if either is already running.
- **Tier 1 cold start**: ~5s (lightweight image, no ML deps). Tier 2 cold start: ~30s (full ML image, GPU allocation).
- **Tier 1 import safety**: The `nic_check_image` doesn't include ML packages (torch, transformers). The check function only imports `nic.config` and `nic.services.gdrive` — neither has ML transitive dependencies.
- **Queued spawns**: If Tier 1 runs while Tier 2 is still processing, `concurrency_limit=1` queues the spawn. The queued worker will start, find no new files (already processed), and exit quickly. Minor GPU cost but safe.
- **Google Drive API rate limit**: 1000 queries/100s. For 500 files: ~500 list + 500 download + 500 move = 1500 queries. Handled by tenacity retry with exponential backoff.
- **R2 dedup safety net**: `images.content_hash` unique index + `ON CONFLICT DO NOTHING` prevents duplicate records even if GDrive move fails and file is re-discovered.
- **`/pipeline/run` unchanged** — still available for processing files uploaded to R2 `images/` via other methods (seed.py, manual upload, etc.).
- **`_IMAGE_EXTENSIONS`** — currently defined in `pipeline.py`. Extract to a shared constant to avoid cross-worker imports.
