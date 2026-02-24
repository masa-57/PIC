"""Shared helpers for worker job management."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from nic.core.database import async_session
from nic.models.db import Job, JobStatus

logger = logging.getLogger(__name__)


async def check_modal_job_status(db: AsyncSession) -> int:
    """Check Modal for failed jobs that still appear PENDING/RUNNING in our DB.

    Polls Modal API for jobs that have a modal_call_id. If Modal reports the
    function call has failed or been cancelled, marks the job as FAILED.
    Returns number of jobs updated.
    """
    result = await db.execute(
        select(Job).where(
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            Job.modal_call_id.isnot(None),
        )
    )
    jobs = result.scalars().all()
    if not jobs:
        return 0

    updated = 0
    for job in jobs:
        try:
            import modal

            assert job.modal_call_id is not None  # Guaranteed by query filter  # noqa: S101
            call = modal.functions.FunctionCall.from_id(job.modal_call_id)
            try:
                call.get(timeout=0)
            except TimeoutError:
                # Still running — this is expected
                continue
            except modal.exception.Error as e:
                # Modal function definitively failed (execution error, timeout, etc.)
                logger.warning("Modal call %s for job %s failed: %s", job.modal_call_id, job.id, e)
                await db.execute(
                    update(Job)
                    .where(Job.id == job.id)
                    .values(
                        status=JobStatus.FAILED,
                        error=f"Modal function failed: {e}",
                        completed_at=datetime.now(UTC),
                    )
                )
                updated += 1
        except Exception:
            logger.warning("Failed to check Modal status for job %s", job.id, exc_info=True)

    if updated:
        await db.commit()
        logger.info("Detected %d failed Modal jobs via polling", updated)
    return updated


async def acquire_advisory_lock(db: AsyncSession, lock_id: int, job_id: str) -> bool:
    """Try to acquire a PostgreSQL advisory lock. If it fails, mark the job as FAILED.

    Returns True if lock was acquired, False otherwise.
    """
    lock_result = await db.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id})
    acquired = lock_result.scalar()
    if not acquired:
        logger.warning("Another job is running (lock %s), failing job %s", hex(lock_id), job_id)
        await mark_job_failed(db, job_id, "Another pipeline or clustering job is already running")
        return False
    return True


async def release_advisory_lock(db: AsyncSession, lock_id: int) -> None:
    """Release advisory lock with error handling for dead connections."""
    try:
        result = await db.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})
        unlocked = result.scalar()
        if not unlocked:
            logger.error("Advisory lock %s was not held when attempting to release", hex(lock_id))
        await db.commit()
    except Exception:
        logger.warning("Failed to release advisory lock %s (connection may be dead)", hex(lock_id), exc_info=True)


@asynccontextmanager
async def advisory_lock(db: AsyncSession, lock_id: int, job_id: str) -> AsyncIterator[None]:
    """Async context manager that acquires and releases a PostgreSQL advisory lock.

    Raises HTTPException(409) if the lock cannot be acquired (another job is running).
    """
    if not await acquire_advisory_lock(db, lock_id, job_id):
        raise RuntimeError(f"Advisory lock {hex(lock_id)} not acquired for job {job_id}")
    try:
        yield
    finally:
        await release_advisory_lock(db, lock_id)


async def mark_job_running(db: AsyncSession, job_id: str) -> None:
    """Set job status to RUNNING with 0% progress."""
    await db.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.RUNNING, progress=0.0))
    await db.commit()


async def mark_job_failed(db: AsyncSession, job_id: str, error: str) -> None:
    """Set job status to FAILED with error message and timestamp."""
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=JobStatus.FAILED,
            error=error,
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()


async def sweep_stale_jobs(db: AsyncSession, max_age_minutes: int | None = None) -> int:
    """Mark RUNNING jobs older than max_age_minutes as FAILED. Returns count swept.

    Defaults to settings.stale_job_timeout_minutes (90min) which exceeds the longest
    Modal function timeout (60min) to avoid false-positive sweeps.
    """
    if max_age_minutes is None:
        from nic.config import settings

        max_age_minutes = settings.stale_job_timeout_minutes
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    result = await db.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.created_at < cutoff)
        .values(
            status=JobStatus.FAILED,
            error=f"Job timed out after {max_age_minutes} minutes",
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()
    swept: int = result.rowcount or 0  # type: ignore[attr-defined]
    if swept:
        logger.warning("Swept %d stale RUNNING jobs (older than %d min)", swept, max_age_minutes)
    return swept


async def mark_job_completed(db: AsyncSession, job_id: str, result: dict[str, object]) -> None:
    """Set job status to COMPLETED with result JSON and timestamp."""
    await db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=JobStatus.COMPLETED,
            progress=1.0,
            result=json.dumps(result),
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()


@asynccontextmanager
async def worker_lifecycle(
    lock_id: int,
    job_id: str,
    worker_name: str,
    statement_timeout: str = "1800s",
) -> AsyncIterator[AsyncSession | None]:
    """Context manager combining advisory lock, job status, error handling, and statement timeout.

    Eliminates boilerplate shared across pipeline, cluster, and gdrive-sync workers:
    1. Opens a DB session
    2. Acquires an advisory lock (fails job if lock unavailable → yields None)
    3. Marks job RUNNING
    4. Sets session statement timeout
    5. Yields the session for the caller to do work
    6. On error: rolls back, marks job FAILED, re-raises
    7. Finally: releases advisory lock

    Callers must check for None: ``async with worker_lifecycle(...) as db: if db is None: return``
    """
    async with async_session() as db:
        if not await acquire_advisory_lock(db, lock_id, job_id):
            yield None
            return

        try:
            await mark_job_running(db, job_id)
            # Session-level timeout survives transaction boundaries in worker phases.
            await db.execute(
                text("SELECT set_config('statement_timeout', :timeout, false)"),
                {"timeout": statement_timeout},
            )
            yield db
        except Exception as e:
            logger.exception("%s failed for job %s", worker_name, job_id)
            try:
                await db.rollback()
            except Exception:
                logger.warning("Rollback failed (connection may be dead)", exc_info=True)
            try:
                await mark_job_failed(db, job_id, str(e))
            except Exception:
                logger.error("Failed to mark job %s as failed", job_id, exc_info=True)
            raise
        finally:
            await release_advisory_lock(db, lock_id)
