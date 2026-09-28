# Local worker backend

Issue: [#112](https://github.com/masa-57/PIC/issues/112) · Status: design approved in chat 2026-09-28, awaiting spec review

## Goal

Run PIC end to end with no cloud accounts: `docker compose up`, copy images
into a folder, trigger the pipeline, get clusters. Modal stays available as an
optional backend for GPU runs.

**Success criteria**

- From a clean clone with only Docker installed, the README quick start
  produces L1 groups and L2 clusters for a folder of images.
- `PIC_WORKER_BACKEND=modal` behaves exactly as today.
- All quality gates pass; new code has unit tests and one integration test.

## Decisions

| Question | Decision |
|---|---|
| Role of Modal | Keep both backends. `local` is the default, `modal` is opt-in. |
| Where local jobs run | A separate `worker` process that polls Postgres. The API image stays slim. |
| How images get in | Drop files into the local storage `images/` folder, then `POST /api/v1/pipeline/run`. No upload endpoint. |

## Design

### 1. Backend selection and dispatch

- New setting `worker_backend: Literal["local", "modal"] = "local"` (`PIC_WORKER_BACKEND`).
- New module `pic/services/dispatch.py` exposes one function:

  ```python
  async def dispatch_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str | None
  ```

  - `modal`: maps the job type to its Modal function name and spawns it with
    `(job_id, params_json)`, as `modal_dispatch.py` does today. Returns the call ID.
  - `local`: returns `None`. The job stays `PENDING` for the local worker to claim.
- `modal_dispatch.py` shrinks to the Modal half of this and is only imported
  when the backend is `modal`, so the API does not need Modal credentials by default.
- Call sites move to `dispatch_job`: cluster, pipeline, URL-ingest and GDrive
  endpoints (via `create_and_dispatch_job`), and the pipeline chaining inside
  the URL-ingest worker.
- Error messages that say "Modal" become backend-neutral.

### 2. Jobs store their parameters

- Alembic migration adds `jobs.params` (JSONB, nullable).
- `create_and_dispatch_job` and the URL-ingest chaining write `params` when
  creating the job.
- Modal functions keep receiving `params_json` as an argument; their
  signatures do not change.

### 3. Local worker

New module `pic/worker/local_runner.py`, exposed as the `pic-worker` console script.

- Loop: every 2 seconds, claim the oldest `PENDING` job whose type the runner
  handles, in one statement:

  ```sql
  UPDATE jobs SET status = 'RUNNING'
  WHERE id = (
    SELECT id FROM jobs
    WHERE status = 'PENDING' AND type IN (:types)
    ORDER BY created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING id, type, params
  ```

- Job type to function, the same functions Modal calls:

  | JobType | Function |
  |---|---|
  | `CLUSTER_FULL` | `pic.worker.cluster.run_cluster` |
  | `PIPELINE` | `pic.worker.pipeline.run_pipeline` |
  | `URL_INGEST` | `pic.worker.url_ingest.run_url_ingest` |
  | `GDRIVE_SYNC` | `pic.worker.gdrive_sync.run_gdrive_sync` |

- One job at a time. The existing advisory lock still serialises pipeline,
  cluster and GDrive jobs.
- A function that raises leaves the job `FAILED` (existing
  `worker_lifecycle` / `mark_job_failed` behaviour); the runner logs it and
  continues. A job still `RUNNING` after its function returns without marking
  it is set `FAILED` with a clear error, so nothing is stuck.
- SIGTERM / SIGINT: finish the current job, then exit.
- The 15-minute GDrive cron stays Modal-only. Locally, GDrive sync runs when
  triggered through its endpoint.

### 4. Docker Compose and images

- Services: `db` (pgvector pg18), `api` (existing slim image), `worker` (new).
- The Dockerfile gains a `worker` target that installs `--extra ml`. On Linux
  the lockfile already resolves CPU-only torch.
- `api` and `worker` both mount `./data` as local storage
  (`PIC_STORAGE_BACKEND=local`). Images go in `./data/images/`.
- The `minio` service is removed.
- README quick start: `docker compose up`, copy images into `data/images/`,
  `curl -X POST .../api/v1/pipeline/run`, browse `/api/v1/clusters/view`.

### 5. GPU use

The embedding code already picks CUDA, then Apple MPS, then CPU.

| How the worker runs | GPU |
|---|---|
| Natively on macOS (`uv run pic-worker`) | Apple Silicon GPU via MPS |
| Docker on macOS | CPU only; Docker cannot reach the Apple GPU |
| Linux with an NVIDIA GPU | CPU only; the lockfile pins CPU torch on Linux |

The README documents the macOS hybrid: `db` and `api` in Compose, worker run
natively. Local NVIDIA support needs CPU/GPU torch variants in the lockfile,
the same problem as #124, and is a roadmap item.

### 6. Simplification in the same change

- Delete the single-image ingest path: Modal `run_ingest`,
  `pic/worker/ingest.py`, `submit_ingest_job`, the unused CLI in
  `pic/worker/entrypoint.py`, and their tests (`test_ingest_worker.py`,
  `test_entrypoint.py`). Nothing else imports them; the pipeline covers ingest.
  `pic-worker` replaces the CLI entry point.
- `scripts/seed.py` becomes: copy files into storage `images/` through the
  storage backend, then call `POST /api/v1/pipeline/run` and poll the job.
  It stops talking to Postgres and Modal directly.

## Testing

- **Unit:** backend selection from settings; `dispatch_job` for both backends
  (Modal mocked); runner claim, dispatch-by-type, failure handling and
  stuck-job handling with worker functions mocked; seed script's API calls.
- **Integration (real Postgres):** two concurrent claims never return the same
  job; `params` round-trips from job creation to the claimed row; migration
  upgrade and downgrade.
- **Manual end to end:** `docker compose up` with a handful of real product
  images produces clusters, and the Mac hybrid run uses MPS.

## Out of scope (roadmap)

Recorded in `ROADMAP.md` as later items:

- A real job queue (Redis, Celery or similar) instead of Postgres polling.
- Parallel job execution in the local worker.
- Local NVIDIA GPU support (CPU/GPU torch variants, shared with #124).
- An image upload endpoint (natural fit for the web UI, #113).
