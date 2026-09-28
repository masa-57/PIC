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
    with patch("pic.services.modal_dispatch.spawn_modal_job", new_callable=AsyncMock, return_value="call-1") as spawn:
        assert await dispatch_job(JobType.CLUSTER_FULL, "job-3", None) == "call-1"
    spawn.assert_awaited_once_with(JobType.CLUSTER_FULL, "job-3", None)


def test_local_job_types_are_the_four_dispatchable_types() -> None:
    assert (
        frozenset({JobType.CLUSTER_FULL, JobType.PIPELINE, JobType.URL_INGEST, JobType.GDRIVE_SYNC}) == LOCAL_JOB_TYPES
    )
