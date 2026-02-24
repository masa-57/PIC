"""Unit tests for Modal dispatch service."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestModalDispatch:
    """Test Modal job dispatch functions."""

    def setup_method(self) -> None:
        """Clear the Modal function cache before each test."""
        from nic.services.modal_dispatch import _get_modal_function

        _get_modal_function.cache_clear()

    @pytest.mark.asyncio
    async def test_submit_ingest_job_success(self):
        """Test successful ingest job submission returns Modal call ID."""
        from nic.services.modal_dispatch import submit_ingest_job

        mock_call = MagicMock()
        mock_call.object_id = "modal-call-123"

        mock_fn = MagicMock()
        mock_fn.spawn.return_value = mock_call

        with patch("modal.Function.from_name", return_value=mock_fn) as mock_from_name:
            result = await submit_ingest_job("img-456", "s3://bucket/key")

            mock_from_name.assert_called_once_with("nic", "run_ingest")
            mock_fn.spawn.assert_called_once_with("img-456")
            assert result == "modal-call-123"

    @pytest.mark.asyncio
    async def test_submit_cluster_job_success_with_params(self):
        """Test successful cluster job submission with parameters."""
        from nic.services.modal_dispatch import submit_cluster_job

        mock_call = MagicMock()
        mock_call.object_id = "modal-call-456"

        mock_fn = MagicMock()
        mock_fn.spawn.return_value = mock_call

        with patch("modal.Function.from_name", return_value=mock_fn) as mock_from_name:
            params = {"min_cluster_size": 5, "min_samples": 3}
            result = await submit_cluster_job("job-789", params)

            mock_from_name.assert_called_once_with("nic", "run_cluster")
            assert mock_fn.spawn.call_count == 1
            call_args = mock_fn.spawn.call_args[0]
            assert call_args[0] == "job-789"
            assert '"min_cluster_size": 5' in call_args[1]
            assert '"min_samples": 3' in call_args[1]
            assert result == "modal-call-456"

    @pytest.mark.asyncio
    async def test_submit_cluster_job_success_no_params(self):
        """Test successful cluster job submission without parameters."""
        from nic.services.modal_dispatch import submit_cluster_job

        mock_call = MagicMock()
        mock_call.object_id = "modal-call-789"

        mock_fn = MagicMock()
        mock_fn.spawn.return_value = mock_call

        with patch("modal.Function.from_name", return_value=mock_fn):
            result = await submit_cluster_job("job-111", None)

            mock_fn.spawn.assert_called_once_with("job-111", None)
            assert result == "modal-call-789"

    @pytest.mark.asyncio
    async def test_submit_pipeline_job_success_with_params(self):
        """Test successful pipeline job submission with parameters."""
        from nic.services.modal_dispatch import submit_pipeline_job

        mock_call = MagicMock()
        mock_call.object_id = "modal-call-pipeline-1"

        mock_fn = MagicMock()
        mock_fn.spawn.return_value = mock_call

        with patch("modal.Function.from_name", return_value=mock_fn) as mock_from_name:
            params = {"min_cluster_size": 10}
            result = await submit_pipeline_job("job-pipeline-1", params)

            mock_from_name.assert_called_once_with("nic", "run_pipeline")
            call_args = mock_fn.spawn.call_args[0]
            assert call_args[0] == "job-pipeline-1"
            assert '"min_cluster_size": 10' in call_args[1]
            assert result == "modal-call-pipeline-1"

    @pytest.mark.asyncio
    async def test_submit_pipeline_job_success_no_params(self):
        """Test successful pipeline job submission without parameters."""
        from nic.services.modal_dispatch import submit_pipeline_job

        mock_call = MagicMock()
        mock_call.object_id = "modal-call-pipeline-2"

        mock_fn = MagicMock()
        mock_fn.spawn.return_value = mock_call

        with patch("modal.Function.from_name", return_value=mock_fn):
            result = await submit_pipeline_job("job-pipeline-2", None)

            mock_fn.spawn.assert_called_once_with("job-pipeline-2", None)
            assert result == "modal-call-pipeline-2"

    @pytest.mark.asyncio
    async def test_submit_ingest_job_modal_connection_error(self):
        """Test that Modal connection errors propagate correctly."""
        from nic.services.modal_dispatch import submit_ingest_job

        with (
            patch("modal.Function.from_name", side_effect=Exception("Modal connection failed")),
            pytest.raises(Exception, match="Modal connection failed"),
        ):
            await submit_ingest_job("img-error", "s3://bucket/error")

    @pytest.mark.asyncio
    async def test_submit_cluster_job_modal_connection_error(self):
        """Test that Modal connection errors propagate for cluster jobs."""
        from nic.services.modal_dispatch import submit_cluster_job

        with (
            patch("modal.Function.from_name", side_effect=Exception("Modal unavailable")),
            pytest.raises(Exception, match="Modal unavailable"),
        ):
            await submit_cluster_job("job-error", {"min_cluster_size": 5})

    @pytest.mark.asyncio
    async def test_submit_pipeline_job_modal_connection_error(self):
        """Test that Modal connection errors propagate for pipeline jobs."""
        from nic.services.modal_dispatch import submit_pipeline_job

        with (
            patch("modal.Function.from_name", side_effect=Exception("Modal timeout")),
            pytest.raises(Exception, match="Modal timeout"),
        ):
            await submit_pipeline_job("job-timeout", None)
