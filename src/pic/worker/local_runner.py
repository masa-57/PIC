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
