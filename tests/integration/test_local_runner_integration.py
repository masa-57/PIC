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
