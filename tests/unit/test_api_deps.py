"""Unit tests for shared API dependency helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.unit
class TestCreateAndDispatchJob:
    @pytest.mark.asyncio
    async def test_records_created_metric_after_job_insert(self) -> None:
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute = AsyncMock(return_value=count_result)

        dispatch_fn = AsyncMock(return_value="modal-call-1")

        with patch("pic.api.deps.record_job_created") as mock_created:
            from pic.api.deps import create_and_dispatch_job
            from pic.models.db import JobType

            job = await create_and_dispatch_job(mock_db, JobType.PIPELINE, dispatch_fn, None)

        assert job.type == JobType.PIPELINE
        mock_created.assert_called_once_with(JobType.PIPELINE)

    @pytest.mark.asyncio
    async def test_records_failed_metric_when_dispatch_fails(self) -> None:
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute = AsyncMock(return_value=count_result)
        dispatch_fn = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("pic.api.deps.record_job_created"),
            patch("pic.api.deps.record_job_finished") as mock_finished,
        ):
            from pic.api.deps import create_and_dispatch_job
            from pic.models.db import JobStatus, JobType

            with pytest.raises(HTTPException, match="Failed to dispatch job"):
                await create_and_dispatch_job(mock_db, JobType.CLUSTER_FULL, dispatch_fn, None)

        mock_finished.assert_called_once_with(JobType.CLUSTER_FULL, JobStatus.FAILED)
