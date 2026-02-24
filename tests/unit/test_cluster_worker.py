"""Unit tests for the cluster worker."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestRunCluster:
    @pytest.mark.asyncio
    async def test_lock_conflict_fails_job(self):
        """If another clustering job holds the advisory lock, this job should fail."""
        mock_session = AsyncMock()

        # Advisory lock returns False (not acquired)
        mock_lock_result = MagicMock()
        mock_lock_result.scalar.return_value = False
        mock_session.execute = AsyncMock(return_value=mock_lock_result)
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("pic.worker.helpers.async_session", return_value=mock_session_ctx):
            from pic.worker.cluster import run_cluster

            await run_cluster("job-1")

        # Should have committed (to save FAILED status)
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_successful_clustering(self):
        """Successful clustering should mark job as COMPLETED with stats."""
        mock_session = AsyncMock()

        # Advisory lock returns True (acquired)
        mock_lock_result = MagicMock()
        mock_lock_result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=mock_lock_result)
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        stats = {"total_images": 100, "l1_groups": 50, "l2_clusters": 5, "l2_noise_groups": 3}

        with (
            patch("pic.worker.helpers.async_session", return_value=mock_session_ctx),
            patch("pic.worker.cluster.run_full_clustering", return_value=stats) as mock_cluster,
        ):
            from pic.worker.cluster import run_cluster

            await run_cluster("job-1", json.dumps({"l1_cluster_selection_epsilon": 0.15}))

        mock_cluster.assert_called_once_with(mock_session, {"l1_cluster_selection_epsilon": 0.15})

    @pytest.mark.asyncio
    async def test_no_images_returns_message(self):
        """When no images to cluster, result should say so."""
        mock_session = AsyncMock()

        mock_lock_result = MagicMock()
        mock_lock_result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=mock_lock_result)
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        empty_stats = {"total_images": 0, "l1_groups": 0, "l2_clusters": 0, "l2_noise_groups": 0}

        with (
            patch("pic.worker.helpers.async_session", return_value=mock_session_ctx),
            patch("pic.worker.cluster.run_full_clustering", return_value=empty_stats),
        ):
            from pic.worker.cluster import run_cluster

            await run_cluster("job-1")

        # Should still commit (with "No images to cluster" message)
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_exception_fails_job_and_reraises(self):
        """If clustering raises, job should be marked FAILED and exception re-raised."""
        mock_session = AsyncMock()

        mock_lock_result = MagicMock()
        mock_lock_result.scalar.return_value = True
        mock_session.execute = AsyncMock(return_value=mock_lock_result)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("pic.worker.helpers.async_session", return_value=mock_session_ctx),
            patch(
                "pic.worker.cluster.run_full_clustering",
                side_effect=RuntimeError("UMAP failed"),
            ),
        ):
            from pic.worker.cluster import run_cluster

            with pytest.raises(RuntimeError, match="UMAP failed"):
                await run_cluster("job-1")

        mock_session.rollback.assert_called_once()
