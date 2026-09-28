# Local Worker Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run PIC end to end with no cloud accounts: `docker compose up`, copy images into `data/images/`, trigger the pipeline, get clusters. Modal stays as an opt-in backend.

**Architecture:** One `dispatch_job()` function routes each new job to the configured backend. The Modal backend spawns the Modal function, exactly as today. The local backend leaves the job `PENDING`; a separate `pic-worker` process polls Postgres, claims jobs with `FOR UPDATE SKIP LOCKED`, and calls the same worker functions Modal calls. Job parameters move onto the job row (`jobs.params`, JSONB) so the local worker can read them.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.1 async + asyncpg, Alembic (psycopg2), PostgreSQL 18 + pgvector, Docker Compose, uv.

**Spec:** `docs/superpowers/specs/2026-09-28-local-worker-backend-design.md`

## Global Constraints

- Setting: `worker_backend: Literal["local", "modal"] = "local"` (env `PIC_WORKER_BACKEND`).
- Local worker polls every 2 seconds and runs one job at a time.
- Local worker handles exactly these job types: `CLUSTER_FULL`, `PIPELINE`, `URL_INGEST`, `GDRIVE_SYNC`.
- Modal function signatures stay `(job_id: str, params_json: str | None)`, except `run_ingest`, which is deleted.
- The 15-minute GDrive cron stays Modal-only.
- Compose services: `db` (`pgvector/pgvector:pg18`), `api`, `worker`. No `minio`.
- Images for the local flow go in `./data/images/`; `./data` is mounted at `/data` and `PIC_LOCAL_STORAGE_PATH=/data`.
- Latest-stable policy (AGENTS.md): Docker uv image moves to `ghcr.io/astral-sh/uv:0.12.19`.
- Every task ends with all five quality gates passing: ruff check, ruff format --check, mypy, `pytest -m unit`, pip-audit --skip-editable.
- Commits must be signed. This repo's local git config already signs with the SSH agent; do not change git config.
- Integration tests need Postgres: `docker compose up db -d` and `PIC_DATABASE_URL=postgresql+asyncpg://pic:pic_local@localhost:5432/pic`. If Docker is unavailable, say so and let CI run them.

## Review Focus

1. **`pic-worker` started while `PIC_WORKER_BACKEND=modal`.** Jobs would run twice, once on Modal and once locally. Expected: the worker refuses to start with a clear message. Test in Task 4.
2. **Worker killed mid-job.** The job would stay `RUNNING` forever. Expected: on the next start, the worker marks orphaned local jobs `FAILED` with a clear error. Test in Task 4.
3. **Job function returns without reaching a terminal status** (for example, the advisory lock was held, or GDrive is not configured). Expected: the job ends `FAILED` with "Worker finished without marking the job completed", and the loop keeps going. Test in Task 4.
4. **Bad or missing `params`** (a URL-ingest row with no `urls`, or `params` NULL on a legacy row). Expected: that job ends `FAILED` with a readable error; the worker keeps running. Test in Task 4.
5. **Compose database host is not `localhost`.** The migration URL builder forces `sslmode=verify-full` for any non-localhost host and overrides even an explicit `sslmode=disable`, so `alembic upgrade head` fails inside Compose. Expected: an explicit `sslmode=disable` is honoured; everything else keeps today's strict default. Test in Task 6.

---

### Task 1: Backend setting and `dispatch_job`

**Files:**
- Modify: `src/pic/config.py` (add `worker_backend`)
- Create: `src/pic/services/dispatch.py`
- Modify: `src/pic/services/modal_dispatch.py` (add `MODAL_FUNCTIONS`, `spawn_modal_job`; keep the old `submit_*` functions until Task 3)
- Test: `tests/unit/test_dispatch.py` (new), `tests/unit/test_modal_dispatch.py` (add tests), `tests/unit/test_config.py` (add tests)

**Interfaces:**
- Produces: `pic.services.dispatch.dispatch_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str | None`
- Produces: `pic.services.dispatch.LOCAL_JOB_TYPES: frozenset[JobType]`
- Produces: `pic.services.modal_dispatch.spawn_modal_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str`
- Produces: `settings.worker_backend: Literal["local", "modal"]`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_dispatch.py`:

```python
"""Unit tests for routing jobs to the configured worker backend."""

from unittest.mock import AsyncMock, patch

import pytest

from pic.models.db import JobType
from pic.services.dispatch import LOCAL_JOB_TYPES, dispatch_job

pytestmark = pytest.mark.unit


async def test_local_backend_leaves_job_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pic.services.dispatch.settings.worker_backend", "local")
    with patch("pic.services.modal_dispatch.spawn_modal_job", new_callable=AsyncMock) as spawn:
        assert await dispatch_job(JobType.PIPELINE, "job-1", {"l2_min_samples": 3}) is None
    spawn.assert_not_awaited()


async def test_local_backend_rejects_job_types_it_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pic.services.dispatch.settings.worker_backend", "local")
    with pytest.raises(ValueError, match="Local worker cannot run"):
        await dispatch_job(JobType.INGEST, "job-2", None)


async def test_modal_backend_spawns_modal_function(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pic.services.dispatch.settings.worker_backend", "modal")
    with patch(
        "pic.services.modal_dispatch.spawn_modal_job", new_callable=AsyncMock, return_value="call-1"
    ) as spawn:
        assert await dispatch_job(JobType.CLUSTER_FULL, "job-3", None) == "call-1"
    spawn.assert_awaited_once_with(JobType.CLUSTER_FULL, "job-3", None)


def test_local_job_types_are_the_four_dispatchable_types() -> None:
    assert frozenset(
        {JobType.CLUSTER_FULL, JobType.PIPELINE, JobType.URL_INGEST, JobType.GDRIVE_SYNC}
    ) == LOCAL_JOB_TYPES
```

Append to `tests/unit/test_modal_dispatch.py` (inside the file's existing unit-marked class or as module-level tests with `@pytest.mark.unit`):

```python
@pytest.mark.unit
class TestSpawnModalJob:
    async def test_maps_job_type_to_function_and_serialises_params(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        fn = MagicMock()
        fn.spawn.return_value = MagicMock(object_id="call-42")
        with patch("pic.services.modal_dispatch._get_modal_function", return_value=fn) as get_fn:
            result = await spawn_modal_job(JobType.PIPELINE, "job-9", {"l1_min_samples": 2})

        assert result == "call-42"
        get_fn.assert_called_once_with("pic", "run_pipeline")
        fn.spawn.assert_called_once_with("job-9", '{"l1_min_samples": 2}')

    async def test_passes_none_when_no_params(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        fn = MagicMock()
        fn.spawn.return_value = MagicMock(object_id="call-43")
        with patch("pic.services.modal_dispatch._get_modal_function", return_value=fn):
            await spawn_modal_job(JobType.URL_INGEST, "job-10", None)
        fn.spawn.assert_called_once_with("job-10", None)

    async def test_unknown_job_type_raises(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        with pytest.raises(ValueError, match="No Modal function"):
            await spawn_modal_job(JobType.CLUSTER_L1, "job-11", None)
```

Add `MagicMock` to that file's `unittest.mock` import if it is missing.

Append to `tests/unit/test_config.py`, constructing `Settings` the same way the existing tests in that file do:

```python
@pytest.mark.unit
class TestWorkerBackend:
    def test_defaults_to_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PIC_WORKER_BACKEND", raising=False)
        from pic.config import Settings

        assert Settings(_env_file=None).worker_backend == "local"

    def test_rejects_unknown_backend(self) -> None:
        from pydantic import ValidationError

        from pic.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, worker_backend="celery")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/unit/test_dispatch.py tests/unit/test_modal_dispatch.py tests/unit/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pic.services.dispatch'` and `ImportError` for `spawn_modal_job`.

- [ ] **Step 3: Add the setting**

In `src/pic/config.py`, add `Literal` to the `typing` import (create `from typing import Literal` if there is no typing import), then add right after the local-storage settings block:

```python
    # Worker backend: "local" = pic-worker process polls Postgres; "modal" = spawn Modal functions
    worker_backend: Literal["local", "modal"] = "local"
```

- [ ] **Step 4: Add `spawn_modal_job` to `modal_dispatch.py`**

Add `from typing import Any` and `from pic.models.db import JobType` to the imports, then add below `_spawn_modal_job`:

```python
# Job type -> Modal function name. Keep in sync with modal_app.py.
MODAL_FUNCTIONS: dict[JobType, str] = {
    JobType.CLUSTER_FULL: MODAL_FN_CLUSTER,
    JobType.PIPELINE: MODAL_FN_PIPELINE,
    JobType.GDRIVE_SYNC: MODAL_FN_GDRIVE_SYNC,
    JobType.URL_INGEST: MODAL_FN_URL_INGEST,
}


@_retry
async def _spawn_with_retry(fn_name: str, job_id: str, params_json: str | None) -> str:
    return _spawn_modal_job(fn_name, job_id, params_json)


async def spawn_modal_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str:
    """Spawn the Modal function for ``job_type``. Returns the Modal call ID."""
    fn_name = MODAL_FUNCTIONS.get(job_type)
    if fn_name is None:
        raise ValueError(f"No Modal function for job type {job_type.value}")
    params_json = json.dumps(params) if params else None
    return await _spawn_with_retry(fn_name, job_id, params_json)
```

- [ ] **Step 5: Create `src/pic/services/dispatch.py`**

```python
"""Route new jobs to the configured worker backend."""

import logging
from typing import Any

from pic.config import settings
from pic.models.db import JobType

logger = logging.getLogger(__name__)

# Job types the local pic-worker can run. Must match RUNNERS in pic.worker.local_runner.
LOCAL_JOB_TYPES: frozenset[JobType] = frozenset(
    {JobType.CLUSTER_FULL, JobType.PIPELINE, JobType.URL_INGEST, JobType.GDRIVE_SYNC}
)


async def dispatch_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str | None:
    """Hand a PENDING job to the worker backend.

    Returns the Modal call ID for the ``modal`` backend. Returns ``None`` for the
    ``local`` backend: the job stays PENDING until a ``pic-worker`` process claims it.
    """
    if settings.worker_backend == "modal":
        # Imported lazily so the API does not need Modal installed or configured by default.
        from pic.services.modal_dispatch import spawn_modal_job

        return await spawn_modal_job(job_type, job_id, params)

    if job_type not in LOCAL_JOB_TYPES:
        raise ValueError(f"Local worker cannot run job type {job_type.value}")
    logger.info("Queued %s job %s for the local worker", job_type.value, job_id)
    return None
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run pytest tests/unit/test_dispatch.py tests/unit/test_modal_dispatch.py tests/unit/test_config.py -q`
Expected: all PASS.

- [ ] **Step 7: Quality gates and commit**

```bash
uv run ruff check src/ tests/ scripts/ && uv run ruff format --check src/ tests/ scripts/ && uv run mypy src/pic/ && uv run pytest -m unit -q
git add src/pic/config.py src/pic/services/dispatch.py src/pic/services/modal_dispatch.py tests/unit/test_dispatch.py tests/unit/test_modal_dispatch.py tests/unit/test_config.py
git commit -m "feat: add PIC_WORKER_BACKEND and dispatch_job (#112)"
```

---

### Task 2: Store job parameters on the job row

**Files:**
- Create: `src/pic/migrations/versions/019_add_job_params.py`
- Modify: `src/pic/models/db.py` (`Job.params`)
- Test: `tests/integration/test_db_operations.py` (add one test)

**Interfaces:**
- Produces: `Job.params: Mapped[dict[str, Any] | None]` (JSONB, nullable)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_db_operations.py`:

```python
@pytest.mark.integration
async def test_job_params_round_trip(db) -> None:
    import uuid

    from sqlalchemy import select

    from pic.models.db import Job, JobStatus, JobType

    job_id = str(uuid.uuid4())
    params = {"urls": ["https://example.com/a.jpg"], "auto_pipeline": True}
    db.add(Job(id=job_id, type=JobType.URL_INGEST, status=JobStatus.PENDING, params=params))
    await db.commit()

    stored = (await db.execute(select(Job.params).where(Job.id == job_id))).scalar_one()
    assert stored == params
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/integration/test_db_operations.py::test_job_params_round_trip -q`
Expected: FAIL with `TypeError: 'params' is an invalid keyword argument for Job`.

- [ ] **Step 3: Add the column to the model**

In `src/pic/models/db.py`, inside `class Job`, directly after the `modal_call_id` line (`JSONB` is already imported; add `Any` to the `typing` import if missing):

```python
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # job input, read by pic-worker
```

- [ ] **Step 4: Add the migration**

`src/pic/migrations/versions/019_add_job_params.py`:

```python
"""Add params JSONB column to jobs.

The local worker reads job input from this column; Modal still receives it as a
function argument.

Revision ID: 7b3e9c2a4f10
Revises: 06d7586a44c8
Create Date: 2026-09-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "7b3e9c2a4f10"
down_revision: str | None = "06d7586a44c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("params", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "params")
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run alembic heads` → Expected: `7b3e9c2a4f10 (head)`.
Run: `uv run pytest tests/integration/test_db_operations.py::test_job_params_round_trip tests/integration/test_migrations.py -q`
Expected: PASS (migration test upgrades to head and downgrades one step).

- [ ] **Step 6: Quality gates and commit**

```bash
uv run ruff check src/ tests/ scripts/ && uv run ruff format --check src/ tests/ scripts/ && uv run mypy src/pic/ && uv run pytest -m unit -q
git add src/pic/models/db.py src/pic/migrations/versions/019_add_job_params.py tests/integration/test_db_operations.py
git commit -m "feat: store job params on the jobs table (#112)"
```

---

### Task 3: Route every job through `dispatch_job`

**Files:**
- Modify: `src/pic/api/deps.py:46-86` (`create_and_dispatch_job`)
- Modify: `src/pic/api/clusters.py:30,67`, `src/pic/api/pipeline.py:14,50`, `src/pic/api/gdrive.py:13,30`, `src/pic/api/images.py:14,74-79`
- Modify: `src/pic/worker/url_ingest.py:97-128` (`_queue_auto_pipeline_job`)
- Modify: `src/pic/services/modal_dispatch.py` (delete the five `submit_*` functions and `MODAL_FN_INGEST`)
- Test: `tests/unit/test_api_deps.py`, `tests/unit/test_api_endpoints.py`, `tests/unit/test_url_ingest.py`, `tests/unit/test_modal_dispatch.py`, `tests/integration/test_images_url_ingest.py`

**Interfaces:**
- Consumes: `dispatch_job` (Task 1), `Job.params` (Task 2)
- Produces: `create_and_dispatch_job(db: AsyncSession, job_type: JobType, params: dict[str, Any] | None = None) -> Job` (the `dispatch_fn` argument is gone)

- [ ] **Step 1: Update the deps tests to the new signature (they will fail)**

Replace the body of `tests/unit/test_api_deps.py` with:

```python
"""Unit tests for shared API dependency helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _mock_db(pending: int = 0) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = pending
    mock_db.execute = AsyncMock(return_value=count_result)
    return mock_db


@pytest.mark.unit
class TestCreateAndDispatchJob:
    async def test_stores_params_and_dispatches(self) -> None:
        from pic.api.deps import create_and_dispatch_job
        from pic.models.db import JobType

        mock_db = _mock_db()
        with (
            patch("pic.api.deps.record_job_created") as mock_created,
            patch("pic.api.deps.dispatch_job", new_callable=AsyncMock, return_value=None) as mock_dispatch,
        ):
            job = await create_and_dispatch_job(mock_db, JobType.PIPELINE, {"l2_min_samples": 4})

        assert job.type == JobType.PIPELINE
        assert job.params == {"l2_min_samples": 4}
        mock_created.assert_called_once_with(JobType.PIPELINE)
        mock_dispatch.assert_awaited_once_with(JobType.PIPELINE, job.id, {"l2_min_samples": 4})

    async def test_records_modal_call_id_when_backend_returns_one(self) -> None:
        from pic.api.deps import create_and_dispatch_job
        from pic.models.db import JobType

        mock_db = _mock_db()
        with (
            patch("pic.api.deps.record_job_created"),
            patch("pic.api.deps.dispatch_job", new_callable=AsyncMock, return_value="modal-call-1"),
        ):
            await create_and_dispatch_job(mock_db, JobType.CLUSTER_FULL)

        # count query + modal_call_id update
        assert mock_db.execute.await_count == 2

    async def test_records_failed_metric_when_dispatch_fails(self) -> None:
        from pic.api.deps import create_and_dispatch_job
        from pic.models.db import JobStatus, JobType

        mock_db = _mock_db()
        with (
            patch("pic.api.deps.record_job_created"),
            patch("pic.api.deps.record_job_finished") as mock_finished,
            patch("pic.api.deps.dispatch_job", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            pytest.raises(HTTPException, match="Failed to dispatch job"),
        ):
            await create_and_dispatch_job(mock_db, JobType.CLUSTER_FULL)

        mock_finished.assert_called_once_with(JobType.CLUSTER_FULL, JobStatus.FAILED)
```

- [ ] **Step 2: Point the other tests at `dispatch_job`**

```bash
sed -i '' 's/patch("pic.api.clusters.submit_cluster_job"/patch("pic.api.deps.dispatch_job"/; s/patch("pic.api.pipeline.submit_pipeline_job"/patch("pic.api.deps.dispatch_job"/' tests/unit/test_api_endpoints.py
sed -i '' 's/"pic.api.images.submit_url_ingest_job"/"pic.api.deps.dispatch_job"/' tests/integration/test_images_url_ingest.py
```

(On Linux use `sed -i` without `''`.)

In `tests/unit/test_url_ingest.py` (around line 139), change the patch target and the argument check:

```python
            patch(
                "pic.services.dispatch.dispatch_job",
                new_callable=AsyncMock,
                return_value="call-123",
            ) as mock_dispatch_job,
```

```python
        mock_dispatch_job.assert_awaited_once()
        job_type, pipeline_job_id, params = mock_dispatch_job.await_args.args
        assert job_type == JobType.PIPELINE
        assert params is None
```

Keep the rest of that test (the `pipeline_job_id != "url-job-1"` and result-payload assertions) unchanged.

In `tests/unit/test_modal_dispatch.py`, delete every test that imports `submit_ingest_job`, `submit_cluster_job`, `submit_pipeline_job`, `submit_gdrive_sync_job` or `submit_url_ingest_job`. Keep `_get_modal_function` tests and the `TestSpawnModalJob` class from Task 1. Then add the connection-error retry case against the new function:

```python
@pytest.mark.unit
async def test_spawn_modal_job_reraises_connection_error_after_retries() -> None:
    from pic.models.db import JobType
    from pic.services.modal_dispatch import spawn_modal_job

    fn = MagicMock()
    fn.spawn.side_effect = ConnectionError("modal down")
    with (
        patch("pic.services.modal_dispatch._get_modal_function", return_value=fn),
        patch("asyncio.sleep", new_callable=AsyncMock),  # skip tenacity's async backoff
        pytest.raises(ConnectionError),
    ):
        await spawn_modal_job(JobType.PIPELINE, "job-x", None)
    assert fn.spawn.call_count == 3
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/unit/test_api_deps.py tests/unit/test_api_endpoints.py tests/unit/test_url_ingest.py -q`
Expected: FAIL (`create_and_dispatch_job` still takes `dispatch_fn`; `pic.api.deps` has no `dispatch_job`).

- [ ] **Step 4: Rewrite `create_and_dispatch_job`**

In `src/pic/api/deps.py`: remove `Callable` from the `collections.abc` import, add `from pic.services.dispatch import dispatch_job`, and replace the function with:

```python
async def create_and_dispatch_job(
    db: AsyncSession,
    job_type: JobType,
    params: dict[str, Any] | None = None,
) -> Job:
    """Create a job record and hand it to the configured worker backend."""
    pending_result = await db.execute(
        select(func.count()).select_from(Job).where(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
    )
    pending_count = int(pending_result.scalar_one())
    if pending_count >= settings.job_queue_max_pending:
        raise HTTPException(
            status_code=429,
            detail=f"Job queue is full ({pending_count} pending/running); try again later",
        )

    job_id = str(uuid.uuid4())
    job = Job(id=job_id, type=job_type, status=JobStatus.PENDING, params=params)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    record_job_created(job_type)

    try:
        call_id = await dispatch_job(job_type, job_id, params)
    except Exception:
        logger.exception("Failed to dispatch %s job %s", job_type.value, job_id)
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=JobStatus.FAILED, error="Failed to dispatch job to worker backend")
        )
        await db.commit()
        record_job_finished(job_type, JobStatus.FAILED)
        raise HTTPException(status_code=503, detail="Failed to dispatch job to compute backend") from None

    if call_id:
        await db.execute(update(Job).where(Job.id == job_id).values(modal_call_id=call_id))
        await db.commit()
        await db.refresh(job)

    return job
```

- [ ] **Step 5: Update the four endpoints**

- `src/pic/api/clusters.py`: delete `from pic.services.modal_dispatch import submit_cluster_job`; change line 67 to
  `job = await create_and_dispatch_job(db, JobType.CLUSTER_FULL, params or None)`
- `src/pic/api/pipeline.py`: delete the `submit_pipeline_job` import; change line 50 to
  `job = await create_and_dispatch_job(db, JobType.PIPELINE, params or None)`
- `src/pic/api/gdrive.py`: delete the `submit_gdrive_sync_job` import; change line 30 to
  `job = await create_and_dispatch_job(db, JobType.GDRIVE_SYNC)`
- `src/pic/api/images.py`: delete the `submit_url_ingest_job` import; change the call to

```python
    job = await create_and_dispatch_job(db, job_type=JobType.URL_INGEST, params=params)
```

- [ ] **Step 6: Update the URL-ingest pipeline chaining**

Replace `_queue_auto_pipeline_job` in `src/pic/worker/url_ingest.py` with:

```python
async def _queue_auto_pipeline_job(db: AsyncSession) -> tuple[str | None, str | None]:
    """Create and dispatch a separate pipeline job for auto-pipeline mode."""
    from pic.models.db import Job
    from pic.services.dispatch import dispatch_job

    pipeline_job_id = str(uuid.uuid4())
    db.add(Job(id=pipeline_job_id, type=JobType.PIPELINE, status=JobStatus.PENDING))
    await db.commit()
    record_job_created(JobType.PIPELINE)

    try:
        call_id = await dispatch_job(JobType.PIPELINE, pipeline_job_id, None)
    except Exception:
        logger.exception("Failed to trigger auto-pipeline job %s", pipeline_job_id)
        await db.execute(
            update(Job)
            .where(Job.id == pipeline_job_id)
            .values(
                status=JobStatus.FAILED,
                error="Failed to dispatch job to worker backend",
                completed_at=datetime.now(UTC),
            )
        )
        await db.commit()
        record_job_finished(JobType.PIPELINE, JobStatus.FAILED)
        return None, "Failed to dispatch auto-pipeline job"

    if call_id:
        await db.execute(update(Job).where(Job.id == pipeline_job_id).values(modal_call_id=call_id))
        await db.commit()

    return pipeline_job_id, None
```

- [ ] **Step 7: Delete the old Modal submit functions**

In `src/pic/services/modal_dispatch.py`, delete `MODAL_FN_INGEST` and the five `submit_*_job` functions. Confirm nothing references them:

Run: `grep -rn "submit_\(ingest\|cluster\|pipeline\|gdrive_sync\|url_ingest\)_job\|MODAL_FN_INGEST" src tests scripts`
Expected: only `scripts/seed.py` may still mention `run_ingest` (rewritten in Task 5); no `submit_*` hits.

- [ ] **Step 8: Run the tests to see them pass**

Run: `uv run pytest -m unit -q`
Expected: all PASS.
Run (Postgres up): `uv run pytest tests/integration/test_images_url_ingest.py -q`
Expected: PASS.

- [ ] **Step 9: Quality gates and commit**

```bash
uv run ruff check src/ tests/ scripts/ && uv run ruff format --check src/ tests/ scripts/ && uv run mypy src/pic/ && uv run pytest -m unit -q
git add src/pic/api src/pic/worker/url_ingest.py src/pic/services/modal_dispatch.py tests/unit tests/integration/test_images_url_ingest.py
git commit -m "refactor: route all jobs through dispatch_job and store params (#112)"
```

---

### Task 4: The local worker (`pic-worker`)

**Files:**
- Create: `src/pic/worker/local_runner.py`
- Modify: `pyproject.toml` (`[project.scripts]`)
- Test: `tests/unit/test_local_runner.py` (new), `tests/integration/test_local_runner_integration.py` (new)

**Interfaces:**
- Consumes: `LOCAL_JOB_TYPES` (Task 1), `Job.params` (Task 2), `pic.worker.helpers.mark_job_failed(db, job_id, error)`, worker functions `run_cluster(job_id, params_json)`, `run_pipeline(job_id, params_json)`, `run_gdrive_sync(job_id, params_json)`, `run_url_ingest(job_id, urls, auto_pipeline=...)`
- Produces: `ClaimedJob(id: str, type: JobType, params: dict[str, Any])`, `RUNNERS: dict[JobType, JobRunner]`, `claim_next_job(db) -> ClaimedJob | None`, `run_job(job) -> None`, `run_once() -> bool`, `recover_orphaned_jobs() -> int`, `run_forever(stop: asyncio.Event, poll_interval: float = 2.0) -> None`, `main() -> None`; console script `pic-worker`

- [ ] **Step 1: Write the failing unit tests**

`tests/unit/test_local_runner.py`:

```python
"""Unit tests for the local pic-worker loop."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pic.models.db import JobType
from pic.services.dispatch import LOCAL_JOB_TYPES
from pic.worker import local_runner
from pic.worker.local_runner import ClaimedJob

pytestmark = pytest.mark.unit


def test_runners_cover_exactly_the_local_job_types() -> None:
    assert frozenset(local_runner.RUNNERS) == LOCAL_JOB_TYPES


async def test_run_job_passes_params_json_to_pipeline_worker() -> None:
    job = ClaimedJob(id="job-1", type=JobType.PIPELINE, params={"l1_min_samples": 2})
    with (
        patch("pic.worker.pipeline.run_pipeline", new_callable=AsyncMock) as run_pipeline,
        patch.object(local_runner, "_finalize", new_callable=AsyncMock) as finalize,
    ):
        await local_runner.run_job(job)
    run_pipeline.assert_awaited_once_with("job-1", '{"l1_min_samples": 2}')
    finalize.assert_awaited_once_with(job, "Worker finished without marking the job completed")


async def test_run_job_passes_none_when_params_empty() -> None:
    job = ClaimedJob(id="job-2", type=JobType.CLUSTER_FULL, params={})
    with (
        patch("pic.worker.cluster.run_cluster", new_callable=AsyncMock) as run_cluster,
        patch.object(local_runner, "_finalize", new_callable=AsyncMock),
    ):
        await local_runner.run_job(job)
    run_cluster.assert_awaited_once_with("job-2", None)


async def test_run_job_unpacks_url_ingest_params() -> None:
    job = ClaimedJob(
        id="job-3", type=JobType.URL_INGEST, params={"urls": ["https://example.com/a.jpg"], "auto_pipeline": True}
    )
    with (
        patch("pic.worker.url_ingest.run_url_ingest", new_callable=AsyncMock) as run_url_ingest,
        patch.object(local_runner, "_finalize", new_callable=AsyncMock),
    ):
        await local_runner.run_job(job)
    run_url_ingest.assert_awaited_once_with("job-3", ["https://example.com/a.jpg"], auto_pipeline=True)


@pytest.mark.parametrize("params", [{}, {"urls": []}, {"urls": "https://x"}, {"urls": [1, 2]}])
async def test_url_ingest_with_bad_params_fails_the_job(params: dict[str, object]) -> None:
    job = ClaimedJob(id="job-4", type=JobType.URL_INGEST, params=params)
    with (
        patch("pic.worker.url_ingest.run_url_ingest", new_callable=AsyncMock) as run_url_ingest,
        patch.object(local_runner, "_finalize", new_callable=AsyncMock) as finalize,
    ):
        await local_runner.run_job(job)
    run_url_ingest.assert_not_awaited()
    error = finalize.await_args.args[1]
    assert error.startswith("ValueError: URL ingest job has no valid 'urls'")


async def test_run_job_records_exception_and_does_not_raise() -> None:
    job = ClaimedJob(id="job-5", type=JobType.PIPELINE, params={})
    with (
        patch("pic.worker.pipeline.run_pipeline", new_callable=AsyncMock, side_effect=RuntimeError("disk full")),
        patch.object(local_runner, "_finalize", new_callable=AsyncMock) as finalize,
    ):
        await local_runner.run_job(job)
    finalize.assert_awaited_once_with(job, "RuntimeError: disk full")


async def test_run_forever_finishes_current_job_then_stops() -> None:
    stop = asyncio.Event()
    calls: list[str] = []

    async def fake_run_once() -> bool:
        calls.append("job")
        stop.set()  # SIGTERM arrives while a job is running
        return True

    with (
        patch.object(local_runner, "recover_orphaned_jobs", new_callable=AsyncMock, return_value=0) as recover,
        patch.object(local_runner, "run_once", side_effect=fake_run_once),
    ):
        await asyncio.wait_for(local_runner.run_forever(stop, poll_interval=0.01), timeout=2)

    recover.assert_awaited_once()
    assert calls == ["job"]


async def test_run_forever_survives_loop_errors() -> None:
    stop = asyncio.Event()
    results = [RuntimeError("db blip"), False]

    async def flaky_run_once() -> bool:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        stop.set()
        return result

    with (
        patch.object(local_runner, "recover_orphaned_jobs", new_callable=AsyncMock, return_value=0),
        patch.object(local_runner, "run_once", side_effect=flaky_run_once),
    ):
        await asyncio.wait_for(local_runner.run_forever(stop, poll_interval=0.01), timeout=2)

    assert results == []


def test_main_refuses_to_start_with_modal_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pic.worker.local_runner.settings.worker_backend", "modal")
    with patch("pic.worker.local_runner.setup_logging"), pytest.raises(SystemExit, match="PIC_WORKER_BACKEND=local"):
        local_runner.main()
```

- [ ] **Step 2: Write the failing integration tests**

`tests/integration/test_local_runner_integration.py`:

```python
"""Integration tests for claiming and finishing jobs against real Postgres."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pic.models.db import Job, JobStatus, JobType
from pic.worker import local_runner

pytestmark = pytest.mark.integration


@pytest.fixture
def runner_sessions(db, db_engine):
    """Point the runner's async_session at the test database (db fixture creates the schema)."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    with patch.object(local_runner, "async_session", factory):
        yield factory


async def _add_job(db, job_type: JobType, status: JobStatus = JobStatus.PENDING, params=None, call_id=None) -> str:
    job_id = str(uuid.uuid4())
    db.add(Job(id=job_id, type=job_type, status=status, params=params, modal_call_id=call_id))
    await db.commit()
    return job_id


async def _status(db, job_id: str) -> JobStatus:
    db.expire_all()
    return (await db.execute(select(Job.status).where(Job.id == job_id))).scalar_one()


async def test_claims_oldest_pending_job_with_params(db, runner_sessions) -> None:
    first = await _add_job(db, JobType.PIPELINE, params={"l2_min_samples": 3})
    await _add_job(db, JobType.CLUSTER_FULL)

    async with runner_sessions() as session:
        claimed = await local_runner.claim_next_job(session)

    assert claimed is not None
    assert claimed.id == first
    assert claimed.type == JobType.PIPELINE
    assert claimed.params == {"l2_min_samples": 3}
    assert await _status(db, first) == JobStatus.RUNNING


async def test_ignores_job_types_it_cannot_run(db, runner_sessions) -> None:
    await _add_job(db, JobType.INGEST)
    async with runner_sessions() as session:
        assert await local_runner.claim_next_job(session) is None


async def test_concurrent_claims_never_return_the_same_job(db, runner_sessions) -> None:
    ids = {await _add_job(db, JobType.PIPELINE), await _add_job(db, JobType.CLUSTER_FULL)}

    async def claim() -> str | None:
        async with runner_sessions() as session:
            job = await local_runner.claim_next_job(session)
            return job.id if job else None

    results = await asyncio.gather(claim(), claim(), claim())
    claimed = [r for r in results if r is not None]
    assert sorted(claimed) == sorted(ids)


async def test_job_left_running_by_worker_function_ends_failed(db, runner_sessions) -> None:
    job_id = await _add_job(db, JobType.CLUSTER_FULL, status=JobStatus.RUNNING)
    job = local_runner.ClaimedJob(id=job_id, type=JobType.CLUSTER_FULL, params={})

    with patch("pic.worker.cluster.run_cluster", new_callable=AsyncMock):  # returns without completing
        await local_runner.run_job(job)

    assert await _status(db, job_id) == JobStatus.FAILED
    error = (await db.execute(select(Job.error).where(Job.id == job_id))).scalar_one()
    assert error == "Worker finished without marking the job completed"


async def test_completed_job_is_left_alone(db, runner_sessions) -> None:
    job_id = await _add_job(db, JobType.CLUSTER_FULL, status=JobStatus.COMPLETED)
    job = local_runner.ClaimedJob(id=job_id, type=JobType.CLUSTER_FULL, params={})
    with patch("pic.worker.cluster.run_cluster", new_callable=AsyncMock):
        await local_runner.run_job(job)
    assert await _status(db, job_id) == JobStatus.COMPLETED


async def test_recover_fails_orphaned_local_jobs_only(db, runner_sessions) -> None:
    orphan = await _add_job(db, JobType.PIPELINE, status=JobStatus.RUNNING)
    modal_job = await _add_job(db, JobType.PIPELINE, status=JobStatus.RUNNING, call_id="fc-123")
    pending = await _add_job(db, JobType.PIPELINE)

    assert await local_runner.recover_orphaned_jobs() == 1

    assert await _status(db, orphan) == JobStatus.FAILED
    assert await _status(db, modal_job) == JobStatus.RUNNING
    assert await _status(db, pending) == JobStatus.PENDING
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run pytest tests/unit/test_local_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'local_runner'`.

- [ ] **Step 4: Implement `src/pic/worker/local_runner.py`**

```python
"""Local worker: claims PENDING jobs from Postgres and runs them in-process.

Start with ``pic-worker``. Only runs when ``PIC_WORKER_BACKEND=local`` (the
default); with the Modal backend, Modal runs the jobs instead.
"""

import asyncio
import contextlib
import json
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pic.config import settings
from pic.core.database import async_session
from pic.core.logging import setup_logging
from pic.models.db import Job, JobStatus, JobType
from pic.worker.helpers import mark_job_failed

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
UNFINISHED_ERROR = "Worker finished without marking the job completed"
ORPHANED_ERROR = "Local worker restarted while the job was running"

JobRunner = Callable[[str, dict[str, Any]], Awaitable[None]]


def _params_json(params: dict[str, Any]) -> str | None:
    return json.dumps(params) if params else None


# Worker modules are imported lazily: they pull in torch / sklearn / umap.
async def _run_cluster(job_id: str, params: dict[str, Any]) -> None:
    from pic.worker.cluster import run_cluster

    await run_cluster(job_id, _params_json(params))


async def _run_pipeline(job_id: str, params: dict[str, Any]) -> None:
    from pic.worker.pipeline import run_pipeline

    await run_pipeline(job_id, _params_json(params))


async def _run_gdrive_sync(job_id: str, params: dict[str, Any]) -> None:
    from pic.worker.gdrive_sync import run_gdrive_sync

    await run_gdrive_sync(job_id, _params_json(params))


async def _run_url_ingest(job_id: str, params: dict[str, Any]) -> None:
    from pic.worker.url_ingest import run_url_ingest

    urls = params.get("urls")
    if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
        raise ValueError("URL ingest job has no valid 'urls' list in params")
    await run_url_ingest(job_id, urls, auto_pipeline=bool(params.get("auto_pipeline", False)))


RUNNERS: dict[JobType, JobRunner] = {
    JobType.CLUSTER_FULL: _run_cluster,
    JobType.PIPELINE: _run_pipeline,
    JobType.GDRIVE_SYNC: _run_gdrive_sync,
    JobType.URL_INGEST: _run_url_ingest,
}


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    type: JobType
    params: dict[str, Any]


async def claim_next_job(db: AsyncSession) -> ClaimedJob | None:
    """Atomically move the oldest runnable PENDING job to RUNNING and return it."""
    next_id = (
        select(Job.id)
        .where(Job.status == JobStatus.PENDING, Job.type.in_(list(RUNNERS)))
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    result = await db.execute(
        update(Job)
        .where(Job.id == next_id)
        .values(status=JobStatus.RUNNING)
        .returning(Job.id, Job.type, Job.params)
        .execution_options(synchronize_session=False)
    )
    row = result.first()
    await db.commit()
    if row is None:
        return None
    return ClaimedJob(id=row.id, type=row.type, params=dict(row.params or {}))


async def _finalize(job: ClaimedJob, error: str) -> None:
    """Mark the job FAILED if the worker function left it PENDING or RUNNING."""
    async with async_session() as db:
        status = (await db.execute(select(Job.status).where(Job.id == job.id))).scalar_one_or_none()
        if status in (JobStatus.PENDING, JobStatus.RUNNING):
            await mark_job_failed(db, job.id, error)
            logger.warning("%s job %s marked FAILED: %s", job.type.value, job.id, error)


async def run_job(job: ClaimedJob) -> None:
    """Run one claimed job. Never raises: a failing job must not stop the worker."""
    logger.info("Running %s job %s", job.type.value, job.id)
    try:
        await RUNNERS[job.type](job.id, job.params)
    except Exception as exc:
        logger.exception("%s job %s raised", job.type.value, job.id)
        await _finalize(job, f"{type(exc).__name__}: {exc}")
        return
    await _finalize(job, UNFINISHED_ERROR)


async def run_once() -> bool:
    """Claim and run one job. Returns False when there was nothing to do."""
    async with async_session() as db:
        job = await claim_next_job(db)
    if job is None:
        return False
    await run_job(job)
    return True


async def recover_orphaned_jobs() -> int:
    """Fail RUNNING local jobs left behind by a worker that died mid-job.

    Modal jobs always have a ``modal_call_id``; local jobs never do.
    """
    async with async_session() as db:
        result = await db.execute(
            select(Job.id).where(
                Job.status == JobStatus.RUNNING,
                Job.modal_call_id.is_(None),
                Job.type.in_(list(RUNNERS)),
            )
        )
        orphan_ids = list(result.scalars())
        for job_id in orphan_ids:
            await mark_job_failed(db, job_id, ORPHANED_ERROR)
    if orphan_ids:
        logger.warning("Marked %d orphaned job(s) FAILED: %s", len(orphan_ids), ", ".join(orphan_ids))
    return len(orphan_ids)


async def run_forever(stop: asyncio.Event, poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
    """Poll for jobs until ``stop`` is set. A job in progress always runs to completion."""
    await recover_orphaned_jobs()
    logger.info("Local worker started; polling every %.1fs", poll_interval)
    while not stop.is_set():
        try:
            ran = await run_once()
        except Exception:
            logger.exception("Worker loop error; retrying after the poll interval")
            ran = False
        if not ran:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=poll_interval)
    logger.info("Local worker stopped")


def main() -> None:
    """Console entry point for ``pic-worker``."""
    setup_logging()
    if settings.worker_backend != "local":
        raise SystemExit(
            f"pic-worker only runs with PIC_WORKER_BACKEND=local (current: {settings.worker_backend}); "
            "with the Modal backend, Modal runs the jobs."
        )

    async def _main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_forever(stop)

    asyncio.run(_main())
```

Check `mark_job_failed` in `src/pic/worker/helpers.py` commits its update. If it does not, add `await db.commit()` after each `mark_job_failed` call in `_finalize` and `recover_orphaned_jobs`.

- [ ] **Step 5: Register the console script**

In `pyproject.toml` under `[project.scripts]`:

```toml
[project.scripts]
pic = "pic.main:main"
pic-worker = "pic.worker.local_runner:main"
```

Run: `uv sync --extra ml && uv run pic-worker --help 2>&1 | head -1 || true` (it ignores args; just confirm the command resolves, then Ctrl-C). Expected: log line "Local worker started" or a DB connection error, not "command not found".

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run pytest tests/unit/test_local_runner.py -q` → Expected: PASS.
Run (Postgres up): `uv run pytest tests/integration/test_local_runner_integration.py -q` → Expected: PASS.

- [ ] **Step 7: Quality gates and commit**

```bash
uv run ruff check src/ tests/ scripts/ && uv run ruff format --check src/ tests/ scripts/ && uv run mypy src/pic/ && uv run pytest -m unit -q
git add src/pic/worker/local_runner.py pyproject.toml uv.lock tests/unit/test_local_runner.py tests/integration/test_local_runner_integration.py
git commit -m "feat: add pic-worker local job runner (#112)"
```

---

### Task 5: Remove single-image ingest; rewrite `seed.py`

**Files:**
- Delete: `src/pic/worker/ingest.py`, `src/pic/worker/entrypoint.py`, `tests/unit/test_ingest_worker.py`, `tests/unit/test_entrypoint.py`
- Modify: `src/pic/modal_app.py` (delete the `run_ingest` Modal function)
- Rewrite: `scripts/seed.py`
- Test: `tests/unit/test_seed_script.py` (new)

**Interfaces:**
- Consumes: `pic.services.storage.get_storage_backend() -> StorageBackend` with `.upload(key: str, data: bytes, content_type: str) -> None`; `POST /api/v1/pipeline/run` → `JobOut` JSON with `id`; `GET /api/v1/jobs/{id}` → `JobOut` JSON with `status` in `pending|running|completed|failed`
- Produces: `scripts/seed.py` functions `find_images(directory: Path) -> list[Path]`, `upload_images(files: list[Path], storage: StorageBackend) -> int`, `start_pipeline(client: httpx.Client) -> str`, `wait_for_job(client: httpx.Client, job_id: str, poll_interval: float, timeout: float) -> str`, `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Delete the single-image ingest path**

```bash
git rm src/pic/worker/ingest.py src/pic/worker/entrypoint.py tests/unit/test_ingest_worker.py tests/unit/test_entrypoint.py
```

In `src/pic/modal_app.py`, delete the whole `@app.function(...)` block and body of `async def run_ingest(image_id: str)`.

Run: `grep -rn "run_ingest\b\|worker.ingest\|worker.entrypoint" src tests`
Expected: no hits (only `run_url_ingest` matches are fine; the `\b` excludes them).

- [ ] **Step 2: Write the failing seed tests**

`tests/unit/test_seed_script.py`:

```python
"""Unit tests for scripts/seed.py."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest

pytestmark = pytest.mark.unit

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"


@pytest.fixture
def seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_script", SEED_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_images_filters_by_extension(seed: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.PNG").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.webp").write_bytes(b"x")

    names = [p.name for p in seed.find_images(tmp_path)]
    assert names == ["a.jpg", "b.PNG", "c.webp"]


def test_upload_images_writes_to_inbox(seed: ModuleType, tmp_path: Path) -> None:
    img = tmp_path / "shoe.jpg"
    img.write_bytes(b"jpeg-bytes")
    storage = MagicMock()

    assert seed.upload_images([img], storage) == 1
    storage.upload.assert_called_once_with("images/shoe.jpg", b"jpeg-bytes", "image/jpeg")


def _client(handler) -> httpx.Client:  # noqa: ANN001
    return httpx.Client(base_url="http://pic.test", transport=httpx.MockTransport(handler))


def test_start_pipeline_returns_job_id(seed: ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/pipeline/run"
        return httpx.Response(202, json={"id": "job-1", "status": "pending"})

    assert seed.start_pipeline(_client(handler)) == "job-1"


def test_wait_for_job_polls_until_terminal(seed: ModuleType) -> None:
    statuses = iter(["pending", "running", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/jobs/job-1"
        return httpx.Response(200, json={"id": "job-1", "status": next(statuses)})

    assert seed.wait_for_job(_client(handler), "job-1", poll_interval=0, timeout=5) == "completed"


def test_wait_for_job_reports_failure(seed: ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "job-1", "status": "failed", "error": "boom"})

    assert seed.wait_for_job(_client(handler), "job-1", poll_interval=0, timeout=5) == "failed"


def test_wait_for_job_times_out(seed: ModuleType) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=json.loads('{"id": "job-1", "status": "running"}'))

    with pytest.raises(TimeoutError):
        seed.wait_for_job(_client(handler), "job-1", poll_interval=0, timeout=0)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/unit/test_seed_script.py -q`
Expected: FAIL with `AttributeError: module 'seed_script' has no attribute 'find_images'` (or an import error for `modal` / `psycopg2`).

- [ ] **Step 4: Rewrite `scripts/seed.py`**

```python
#!/usr/bin/env python3
"""Upload a folder of images to PIC storage and run the pipeline.

Usage:
    python scripts/seed.py /path/to/images/
    python scripts/seed.py /path/to/images/ --api http://localhost:8000 --no-cluster

Copies images into the storage backend's ``images/`` inbox (S3, GCS or local,
per your PIC_* settings), then calls ``POST /api/v1/pipeline/run`` and waits
for the job to finish. With docker compose and local storage you can skip this
script and copy files into ``data/images/`` directly.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from pic.config import settings  # noqa: E402
from pic.core.constants import IMAGE_EXTENSIONS, S3_PREFIX_INBOX  # noqa: E402
from pic.services.storage import get_storage_backend  # noqa: E402
from pic.services.storage.base import StorageBackend  # noqa: E402

POLL_INTERVAL_SECONDS = 5.0
TIMEOUT_SECONDS = 3600.0
TERMINAL_STATUSES = {"completed", "failed"}
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def find_images(directory: Path) -> list[Path]:
    """All image files under ``directory``, sorted by name."""
    files = [p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(files, key=lambda p: p.name)


def upload_images(files: list[Path], storage: StorageBackend) -> int:
    """Upload each file to ``images/<name>``. Returns the number uploaded."""
    for i, path in enumerate(files, 1):
        key = f"{S3_PREFIX_INBOX}{path.name}"
        storage.upload(key, path.read_bytes(), CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        print(f"  [{i}/{len(files)}] {path.name} -> {key}")
    return len(files)


def start_pipeline(client: httpx.Client) -> str:
    """Trigger the pipeline and return its job ID."""
    response = client.post("/api/v1/pipeline/run", json={})
    response.raise_for_status()
    return str(response.json()["id"])


def wait_for_job(
    client: httpx.Client,
    job_id: str,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = TIMEOUT_SECONDS,
) -> str:
    """Poll the job until it completes or fails. Returns the final status."""
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in TERMINAL_STATUSES:
            if job["status"] == "failed":
                print(f"Job {job_id} failed: {job.get('error')}")
            return str(job["status"])
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Job {job_id} still {job['status']} after {timeout:.0f}s")
        time.sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload images and run the PIC pipeline")
    parser.add_argument("directory", type=Path, help="Directory containing images")
    parser.add_argument("--api", default="http://localhost:8000", help="PIC API base URL")
    parser.add_argument("--no-cluster", action="store_true", help="Upload only; do not run the pipeline")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory")
        return 1
    files = find_images(args.directory)
    if not files:
        print(f"No image files found in {args.directory}")
        return 0

    print(f"Uploading {len(files)} images to the {settings.storage_backend} storage inbox")
    upload_images(files, get_storage_backend())
    if args.no_cluster:
        print("Skipping the pipeline (--no-cluster). Run POST /api/v1/pipeline/run when ready.")
        return 0

    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    with httpx.Client(base_url=args.api, headers=headers, timeout=30) as client:
        job_id = start_pipeline(client)
        print(f"Pipeline job {job_id} started; waiting for it to finish...")
        status = wait_for_job(client, job_id)
    print(f"Pipeline job {job_id}: {status}")
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/unit/test_seed_script.py -q` → Expected: PASS.

- [ ] **Step 6: Quality gates and commit**

```bash
uv run ruff check src/ tests/ scripts/ && uv run ruff format --check src/ tests/ scripts/ && uv run mypy src/pic/ && uv run pytest -m unit -q
git add -A src/pic/modal_app.py src/pic/worker scripts/seed.py tests/unit
git commit -m "refactor: drop single-image ingest path; seed.py uses storage + pipeline API (#112)"
```

---

### Task 6: Docker Compose stack

**Files:**
- Create: `src/pic/core/db_url.py`
- Modify: `src/pic/migrations/env.py` (use the new helper)
- Modify: `src/pic/core/database.py:35-38` (no warning for explicit `sslmode=disable`)
- Modify: `pyproject.toml` (move `psycopg2-binary` from dev to main dependencies)
- Rewrite: `Dockerfile` (`api` + `worker` targets); modify `Dockerfile.railway` (uv image bump only)
- Rewrite: `docker-compose.yml`
- Modify: `.gitignore` (ignore `data/`)
- Test: `tests/unit/test_db_url.py` (new)

**Interfaces:**
- Produces: `pic.core.db_url.migration_url(url: str, ssl_ca: str = "") -> str`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_db_url.py`:

```python
"""Unit tests for the Alembic database URL builder."""

import pytest

from pic.core.db_url import migration_url

pytestmark = pytest.mark.unit


def test_converts_asyncpg_to_psycopg2() -> None:
    assert migration_url("postgresql+asyncpg://u:p@localhost:5432/pic") == "postgresql+psycopg2://u:p@localhost:5432/pic"


def test_remote_host_defaults_to_verify_full() -> None:
    url = migration_url("postgresql+asyncpg://u:p@db.example.com:5432/pic")
    assert url.endswith("?sslmode=verify-full")


def test_remote_host_upgrades_weak_sslmode() -> None:
    url = migration_url("postgresql+asyncpg://u:p@db.example.com/pic?sslmode=require")
    assert url.endswith("?sslmode=verify-full")


def test_explicit_disable_is_honoured() -> None:
    url = migration_url("postgresql+asyncpg://pic:pic_local@db:5432/pic?sslmode=disable")
    assert url == "postgresql+psycopg2://pic:pic_local@db:5432/pic?sslmode=disable"


def test_ssl_ca_added_for_remote_host() -> None:
    url = migration_url("postgresql+asyncpg://u:p@db.example.com/pic", ssl_ca="/certs/ca.pem")
    assert "sslrootcert=%2Fcerts%2Fca.pem" in url
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_db_url.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pic.core.db_url'`.

- [ ] **Step 3: Add the helper and use it from Alembic**

`src/pic/core/db_url.py` (no settings import, so Alembic can use it before settings load):

```python
"""Build the synchronous database URL Alembic uses."""

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

LOCAL_HOSTS = ("localhost", "127.0.0.1", None)
STRICT_SSLMODES = {"verify-full", "verify-ca"}


def migration_url(url: str, ssl_ca: str = "") -> str:
    """Convert an asyncpg URL to psycopg2 with production-safe TLS defaults.

    Remote hosts get ``sslmode=verify-full`` unless the URL already asks for
    ``verify-full``/``verify-ca`` or explicitly opts out with ``sslmode=disable``
    (used by the docker compose ``db`` host).
    """
    # Explicit driver: SQLAlchemy 2.1 maps a bare postgresql:// to psycopg 3, which is not installed.
    sync_url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    parts = urlsplit(sync_url)
    params = parse_qs(parts.query)

    if parts.hostname not in LOCAL_HOSTS:
        sslmode = params.get("sslmode", [None])[0]
        if sslmode != "disable" and sslmode not in STRICT_SSLMODES:
            params["sslmode"] = ["verify-full"]
        if ssl_ca and sslmode != "disable":
            params["sslrootcert"] = [ssl_ca]

    query = urlencode({k: v[0] for k, v in params.items()}) if params else ""
    return urlunsplit(parts._replace(query=query))
```

In `src/pic/migrations/env.py`, replace the body of `get_sync_url()` with:

```python
def get_sync_url() -> str:
    """Get synchronous database URL for migrations with production-safe TLS defaults."""
    from pic.core.db_url import migration_url

    url = os.environ.get("PIC_DATABASE_URL", "postgresql+psycopg2://localhost:5432/pic")
    return migration_url(url, os.environ.get("PIC_DB_SSL_CA", "").strip())
```

Remove the now-unused `urllib.parse` imports from `env.py`.

In `src/pic/core/database.py`, change the warning branch so an explicit opt-out is silent:

```python
    elif sslmode != "disable" and parts.hostname not in ("localhost", "127.0.0.1", None):
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/unit/test_db_url.py tests/unit/test_database.py -q` → Expected: PASS.

- [ ] **Step 5: Make migrations runnable in the API image**

In `pyproject.toml`, delete `"psycopg2-binary>=2.9",` from `[dependency-groups] dev` and add it to `[project] dependencies` under the `# Database` group:

```toml
    "psycopg2-binary>=2.9",  # sync driver for Alembic migrations
```

Run: `uv lock && uv sync --extra ml`

- [ ] **Step 6: Rewrite `Dockerfile`**

```dockerfile
# PIC images: `api` (slim, no ML deps) and `worker` (local job runner with ML deps).
# On Linux the lockfile resolves CPU-only torch, so the worker image has no CUDA.

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos '' --uid 1001 appuser
WORKDIR /app
COPY pyproject.toml uv.lock ./

FROM base AS api
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md alembic.ini ./
COPY src/ src/
RUN uv sync --frozen --no-dev
USER appuser
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1
CMD uv run --no-sync fastapi run src/pic/main.py --host 0.0.0.0 --port $PORT

FROM base AS worker
RUN uv sync --frozen --no-dev --extra ml --no-install-project
COPY README.md ./
COPY src/ src/
RUN uv sync --frozen --no-dev --extra ml
# DINOv2 weights download here on first run; compose mounts a volume so it happens once.
RUN mkdir -p /home/appuser/.cache/huggingface && chown -R appuser:appuser /home/appuser/.cache
USER appuser
CMD ["uv", "run", "--no-sync", "pic-worker"]
```

In `Dockerfile.railway`, change `ghcr.io/astral-sh/uv:0.9.30` to `ghcr.io/astral-sh/uv:0.12.19`.

- [ ] **Step 7: Rewrite `docker-compose.yml`**

```yaml
# Local stack: Postgres + API + local worker. No cloud accounts needed.
#   mkdir -p data/images && docker compose up --build
#   cp /path/to/photos/*.jpg data/images/
#   curl -X POST http://localhost:8000/api/v1/pipeline/run
x-pic-env: &pic-env
  PIC_DATABASE_URL: postgresql+asyncpg://pic:pic_local@db:5432/pic?sslmode=disable
  PIC_STORAGE_BACKEND: local
  PIC_LOCAL_STORAGE_PATH: /data
  PIC_LOCAL_STORAGE_BASE_URL: http://localhost:8000/files
  PIC_WORKER_BACKEND: local
  PIC_AUTH_DISABLED: "true"  # Dev only: no API key needed locally

services:
  db:
    image: pgvector/pgvector:pg18
    environment:
      POSTGRES_DB: pic
      POSTGRES_USER: pic
      POSTGRES_PASSWORD: pic_local  # Dev only — not used in production
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pic"]
      interval: 5s
      timeout: 3s
      retries: 5

  api:
    build:
      context: .
      target: api
    command: sh -c "uv run --no-sync alembic upgrade head && uv run --no-sync fastapi run src/pic/main.py --host 0.0.0.0 --port 8000"
    ports:
      - "8000:8000"
    environment: *pic-env
    volumes:
      - ./data:/data
    depends_on:
      db:
        condition: service_healthy

  worker:
    build:
      context: .
      target: worker
    environment: *pic-env
    volumes:
      - ./data:/data
      - hf-cache:/home/appuser/.cache/huggingface
    depends_on:
      api:
        condition: service_healthy  # api runs migrations before it reports healthy
    stop_grace_period: 5m  # let an in-flight job finish on docker compose stop

volumes:
  pgdata:
  hf-cache:
```

Note: `pgvector/pgvector:pg18` stores data under `/var/lib/postgresql` (pg18 layout), not `/var/lib/postgresql/data`.

Add to `.gitignore`:

```
# Local storage for docker compose (images, thumbnails)
data/
```

- [ ] **Step 8: Build and smoke-test the stack**

```bash
mkdir -p data/images
docker compose build
docker compose up -d
docker compose ps          # expect db healthy, api healthy, worker running
docker compose logs worker | tail -5   # expect "Local worker started; polling every 2.0s"
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok"...}` from `/health`; worker log shows it started. If Docker is not running, say so and stop at this step; do not mark the task complete.

- [ ] **Step 9: Quality gates and commit**

```bash
uv run ruff check src/ tests/ scripts/ && uv run ruff format --check src/ tests/ scripts/ && uv run mypy src/pic/ && uv run pytest -m unit -q && uv run pip-audit --skip-editable
git add src/pic/core/db_url.py src/pic/core/database.py src/pic/migrations/env.py pyproject.toml uv.lock Dockerfile Dockerfile.railway docker-compose.yml .gitignore tests/unit/test_db_url.py
git commit -m "feat: docker compose stack with local worker; honour sslmode=disable in migrations (#112)"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md` (Quick Start, Architecture flows, new "Using your Mac's GPU" section, Configuration table)
- Modify: `AGENTS.md` (Commands, Architecture, Code Structure, Gotchas)
- Modify: `.env.example`, `CHANGELOG.md`, `docs/deployment/self-hosted.md`, `docs/deployment/modal-setup.md`

- [ ] **Step 1: README quick start**

Replace the Quick Start section's command block with:

```bash
# Prerequisites: Docker. Nothing else.
git clone https://github.com/masa-57/PIC.git
cd PIC
mkdir -p data/images
docker compose up --build -d

# Add images and run the pipeline
cp /path/to/product/photos/*.jpg data/images/
curl -X POST http://localhost:8000/api/v1/pipeline/run

# Watch progress, then browse the clusters
curl http://localhost:8000/api/v1/jobs
open http://localhost:8000/api/v1/clusters/view
```

Add below it:

```markdown
The first pipeline run downloads the DINOv2 model (about 350 MB) into a Docker volume; later runs reuse it.
On Linux, if the worker cannot write to `data/`, run `sudo chown -R 1001 data` (the containers run as uid 1001).

### Using your Mac's GPU

Docker on macOS cannot reach the Apple GPU, so the worker runs on CPU in Compose.
To use the GPU, run the database and API in Docker and the worker natively:

    docker compose up -d db api
    uv sync --extra ml
    PIC_DATABASE_URL=postgresql+asyncpg://pic:pic_local@localhost:5432/pic \
    PIC_STORAGE_BACKEND=local PIC_LOCAL_STORAGE_PATH=./data \
    uv run pic-worker

The embedding code picks Apple's MPS device automatically.

### Running on Modal instead

Set `PIC_WORKER_BACKEND=modal` on the API and deploy the Modal app (see `docs/deployment/modal-setup.md`).
Do not run `pic-worker` in that mode.
```

In the Architecture "Flows" list, replace the Ingestion bullet with:
`- **Jobs**: the API records each job, then either leaves it for the local `pic-worker` (default) or spawns a Modal function (`PIC_WORKER_BACKEND=modal`). Both run the same worker code.`

Add `PIC_WORKER_BACKEND` to the Configuration table: `| PIC_WORKER_BACKEND | Where jobs run: local (pic-worker, default) or modal |`.

- [ ] **Step 2: AGENTS.md**

- Commands: add `docker compose up --build -d   # db + api + local worker` and `uv run pic-worker   # run the local worker natively (uses Apple GPU on macOS)`.
- Architecture: replace the "Ingestion flow" paragraph with a "Job flow" paragraph: API creates the job with `params`; `dispatch_job()` either leaves it PENDING for `pic-worker` (`PIC_WORKER_BACKEND=local`, default) or spawns the Modal function. Note that the single-image ingest path was removed; the pipeline does discover + dedup + ingest + cluster.
- Code Structure: add `src/pic/services/dispatch.py -- routes jobs to the local or Modal backend`, `src/pic/worker/local_runner.py -- pic-worker: claims PENDING jobs with SKIP LOCKED and runs them`, `src/pic/core/db_url.py -- Alembic URL builder`; remove the `entrypoint.py` line.
- Gotchas: fix the advisory lock value to `0x4E494301` (both lines that say `0x50494301`); add `- pic-worker refuses to start unless PIC_WORKER_BACKEND=local, so a job never runs on both backends`; add `- Existing Modal deployments must set PIC_WORKER_BACKEND=modal; the default is local`.

- [ ] **Step 3: .env.example, CHANGELOG, deployment docs**

`.env.example`: add
```
# Where jobs run: local (pic-worker process, default) or modal
PIC_WORKER_BACKEND=local
```

`CHANGELOG.md`, under `## [Unreleased]`:
```markdown
### Added
- Local worker backend: `pic-worker` runs jobs from Postgres; `docker compose up` gives a full stack with no cloud accounts (#112)
- `PIC_WORKER_BACKEND` setting (`local` default, `modal`) and `jobs.params` column (#112)

### Changed
- **Breaking:** jobs no longer go to Modal by default. Existing Modal deployments must set `PIC_WORKER_BACKEND=modal` (#112)
- `scripts/seed.py` uploads through the storage backend and triggers the pipeline API (#112)
- `psycopg2-binary` is a runtime dependency so migrations run in the API image

### Removed
- Single-image ingest path (`run_ingest` Modal function, `pic.worker.ingest`, worker CLI entrypoint) (#112)
- MinIO from docker compose; local storage replaces it
```

`docs/deployment/self-hosted.md`: replace the opening "best-effort guidance ... roadmap" sentence and the Celery/Dramatiq bullet with a pointer to the README quick start and `pic-worker`.

`docs/deployment/modal-setup.md`: add a line near the top: "Set `PIC_WORKER_BACKEND=modal` on the API; the default `local` backend never contacts Modal."

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md .env.example CHANGELOG.md docs/deployment
git commit -m "docs: local worker quick start, Mac GPU setup, backend switch (#112)"
```

---

### Task 8: End-to-end verification

**Files:** none (verification only). Needs Docker running.

- [ ] **Step 1: Clean start**

```bash
docker compose down -v
rm -rf data && mkdir -p data/images
docker compose up --build -d
docker compose ps
```

Expected: `db` healthy, `api` healthy, `worker` running.

- [ ] **Step 2: Folder flow**

Copy 10 to 30 product photos into `data/images/`, including at least two shots of the same product and one exact duplicate file under a different name. If no photos are at hand, ask the user for a folder.

```bash
JOB=$(curl -s -X POST http://localhost:8000/api/v1/pipeline/run | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
until curl -s http://localhost:8000/api/v1/jobs/$JOB | grep -Eq '"status":"(completed|failed)"'; do sleep 5; done
curl -s http://localhost:8000/api/v1/jobs/$JOB
ls data/processed data/rejected
curl -s "http://localhost:8000/api/v1/clusters/l1?limit=5"
```

Expected: job `completed`; originals moved to `data/processed/`; the duplicate in `data/rejected/`; at least one L1 group with 2+ members; `/api/v1/clusters/view` renders thumbnails in a browser.

- [ ] **Step 3: URL-ingest chaining**

```bash
curl -s -X POST http://localhost:8000/api/v1/images/ingest \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://picsum.photos/id/1/600/400","https://picsum.photos/id/2/600/400"],"auto_pipeline":true}'
```

Poll `/api/v1/jobs` until the URL-ingest job and the pipeline job it spawns are both `completed`.

- [ ] **Step 4: Restart recovery**

Start a pipeline job, then `docker compose restart worker` while it runs. Expected: after restart the worker logs "Marked 1 orphaned job(s) FAILED", and a new pipeline job then completes.

- [ ] **Step 5: macOS GPU (on the Mac only)**

```bash
docker compose stop worker
uv sync --extra ml
uv run python -c "from pic.services.embedding import _get_device; print(_get_device())"
```

Expected: `mps`. Then run `pic-worker` natively as in the README section and confirm a pipeline job completes.

- [ ] **Step 6: Record results**

Post the outcome of steps 2 to 5 as a comment on issue #112 (`gh issue comment 112 --body ...`), including anything that did not match the expectations.
