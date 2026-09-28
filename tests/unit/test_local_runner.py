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
