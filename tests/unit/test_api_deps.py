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
