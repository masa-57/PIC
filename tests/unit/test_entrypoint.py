"""Unit tests for the worker entrypoint (AWS Batch dispatcher)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestEntrypoint:
    def test_ingest_command_calls_run_ingest(self):
        """Ingest command should dispatch to run_ingest via asyncio.run."""
        mock_run_ingest = MagicMock()
        mock_coro = MagicMock()
        mock_run_ingest.return_value = mock_coro

        with (
            patch("sys.argv", ["entrypoint", "ingest", "--image-id", "img-123"]),
            patch("nic.worker.entrypoint.setup_logging"),
            patch("nic.worker.ingest.run_ingest", mock_run_ingest),
            patch("asyncio.run") as mock_asyncio_run,
        ):
            from nic.worker.entrypoint import main

            main()

        mock_run_ingest.assert_called_once_with("img-123")
        mock_asyncio_run.assert_called_once_with(mock_coro)

    def test_cluster_command_calls_run_cluster(self):
        """Cluster command should dispatch to run_cluster via asyncio.run."""
        mock_run_cluster = MagicMock()
        mock_coro = MagicMock()
        mock_run_cluster.return_value = mock_coro

        with (
            patch("sys.argv", ["entrypoint", "cluster", "--job-id", "job-456"]),
            patch("nic.worker.entrypoint.setup_logging"),
            patch("nic.worker.cluster.run_cluster", mock_run_cluster),
            patch("asyncio.run") as mock_asyncio_run,
        ):
            from nic.worker.entrypoint import main

            main()

        mock_run_cluster.assert_called_once_with("job-456", None)
        mock_asyncio_run.assert_called_once_with(mock_coro)

    def test_cluster_command_passes_params(self):
        """Cluster command should forward --params to run_cluster."""
        mock_run_cluster = MagicMock()
        mock_coro = MagicMock()
        mock_run_cluster.return_value = mock_coro
        params_json = '{"min_cluster_size": 10}'

        with (
            patch(
                "sys.argv",
                ["entrypoint", "cluster", "--job-id", "job-456", "--params", params_json],
            ),
            patch("nic.worker.entrypoint.setup_logging"),
            patch("nic.worker.cluster.run_cluster", mock_run_cluster),
            patch("asyncio.run") as mock_asyncio_run,
        ):
            from nic.worker.entrypoint import main

            main()

        mock_run_cluster.assert_called_once_with("job-456", params_json)
        mock_asyncio_run.assert_called_once_with(mock_coro)

    def test_missing_command_exits(self):
        """Missing subcommand should cause SystemExit from argparse."""
        with (
            patch("sys.argv", ["entrypoint"]),
            patch("nic.worker.entrypoint.setup_logging"),
        ):
            from nic.worker.entrypoint import main

            with pytest.raises(SystemExit):
                main()

    def test_ingest_missing_image_id_exits(self):
        """Ingest without --image-id should cause SystemExit from argparse."""
        with (
            patch("sys.argv", ["entrypoint", "ingest"]),
            patch("nic.worker.entrypoint.setup_logging"),
        ):
            from nic.worker.entrypoint import main

            with pytest.raises(SystemExit):
                main()

    def test_cluster_missing_job_id_exits(self):
        """Cluster without --job-id should cause SystemExit from argparse."""
        with (
            patch("sys.argv", ["entrypoint", "cluster"]),
            patch("nic.worker.entrypoint.setup_logging"),
        ):
            from nic.worker.entrypoint import main

            with pytest.raises(SystemExit):
                main()
