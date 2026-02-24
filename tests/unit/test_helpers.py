"""Unit tests for worker helper functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestSweepStaleJobs:
    """Tests for sweep_stale_jobs helper."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    async def test_sweeps_stale_running_jobs(self, mock_db):
        from nic.worker.helpers import sweep_stale_jobs

        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_db.execute = AsyncMock(return_value=mock_result)

        swept = await sweep_stale_jobs(mock_db, max_age_minutes=60)

        assert swept == 2
        mock_db.commit.assert_awaited_once()

    async def test_no_stale_jobs_returns_zero(self, mock_db):
        from nic.worker.helpers import sweep_stale_jobs

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        swept = await sweep_stale_jobs(mock_db, max_age_minutes=60)

        assert swept == 0
        mock_db.commit.assert_awaited_once()

    async def test_custom_max_age(self, mock_db):
        from nic.worker.helpers import sweep_stale_jobs

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_result)

        swept = await sweep_stale_jobs(mock_db, max_age_minutes=30)

        assert swept == 1
        # Verify the update was called (SQL includes the custom timeout message)
        mock_db.execute.assert_awaited_once()

    async def test_default_max_age_is_60(self, mock_db):
        from nic.worker.helpers import sweep_stale_jobs

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        swept = await sweep_stale_jobs(mock_db)

        assert swept == 0


@pytest.mark.unit
class TestMarkJobHelpers:
    """Tests for mark_job_running, mark_job_failed, mark_job_completed."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    async def test_mark_job_running(self, mock_db):
        from nic.worker.helpers import mark_job_running

        await mark_job_running(mock_db, "job-1")

        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    async def test_mark_job_failed(self, mock_db):
        from nic.worker.helpers import mark_job_failed

        await mark_job_failed(mock_db, "job-1", "something went wrong")

        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    async def test_mark_job_completed(self, mock_db):
        from nic.worker.helpers import mark_job_completed

        await mark_job_completed(mock_db, "job-1", {"images_processed": 10})

        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()


@pytest.mark.unit
class TestAcquireAdvisoryLock:
    """Tests for acquire_advisory_lock."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    async def test_lock_acquired(self, mock_db):
        from nic.worker.helpers import acquire_advisory_lock

        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        mock_db.execute = AsyncMock(return_value=mock_result)

        acquired = await acquire_advisory_lock(mock_db, 0x4E494301, "job-1")

        assert acquired is True

    async def test_lock_not_acquired_marks_job_failed(self, mock_db):
        from nic.worker.helpers import acquire_advisory_lock

        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        mock_db.execute = AsyncMock(return_value=mock_result)

        acquired = await acquire_advisory_lock(mock_db, 0x4E494301, "job-1")

        assert acquired is False
        # Should have called execute twice: once for lock, once for marking failed
        assert mock_db.execute.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_lifecycle_sets_session_statement_timeout() -> None:
    from nic.worker.helpers import worker_lifecycle

    db = AsyncMock()
    db.execute = AsyncMock()

    with (
        patch("nic.worker.helpers.async_session") as mock_session,
        patch("nic.worker.helpers.acquire_advisory_lock", new_callable=AsyncMock) as mock_lock,
        patch("nic.worker.helpers.mark_job_running", new_callable=AsyncMock) as mock_running,
        patch("nic.worker.helpers.release_advisory_lock", new_callable=AsyncMock) as mock_release,
    ):
        mock_lock.return_value = True
        mock_session.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        async with worker_lifecycle(0x4E494301, "job-1", "worker", statement_timeout="30s") as yielded_db:
            assert yielded_db is db

    mock_running.assert_awaited_once_with(db, "job-1")
    db.execute.assert_awaited_once()
    sql_text = str(db.execute.await_args.args[0]).lower()
    assert "set_config('statement_timeout'" in sql_text
    assert "set local statement_timeout" not in sql_text
    assert db.execute.await_args.args[1]["timeout"] == "30s"
    mock_release.assert_awaited_once_with(db, 0x4E494301)
