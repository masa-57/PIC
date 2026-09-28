"""Unit tests for the Modal dispatch backend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestSpawnModalJob:
    def setup_method(self) -> None:
        """Clear the Modal function cache before each test."""
        from pic.services.modal_dispatch import _get_modal_function

        _get_modal_function.cache_clear()

    async def test_maps_job_type_to_function_and_serialises_params(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        fn = MagicMock()
        fn.spawn.return_value = MagicMock(object_id="call-42")
        with patch("pic.services.modal_dispatch._get_modal_function", return_value=fn) as get_fn:
            result = await spawn_modal_job(JobType.PIPELINE, "job-9", {"l1_min_samples": 2})

        assert result == "call-42"
        get_fn.assert_called_once_with("pic", "run_pipeline")
        fn.spawn.assert_called_once_with("job-9", '{"l1_min_samples": 2}')

    async def test_passes_none_when_no_params(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        fn = MagicMock()
        fn.spawn.return_value = MagicMock(object_id="call-43")
        with patch("pic.services.modal_dispatch._get_modal_function", return_value=fn):
            await spawn_modal_job(JobType.URL_INGEST, "job-10", None)
        fn.spawn.assert_called_once_with("job-10", None)

    async def test_unknown_job_type_raises(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        with pytest.raises(ValueError, match="No Modal function"):
            await spawn_modal_job(JobType.CLUSTER_L1, "job-11", None)

    async def test_function_lookup_is_cached(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        fn = MagicMock()
        fn.spawn.return_value = MagicMock(object_id="call-44")
        with patch("modal.Function.from_name", return_value=fn) as from_name:
            await spawn_modal_job(JobType.CLUSTER_FULL, "job-12", None)
            await spawn_modal_job(JobType.CLUSTER_FULL, "job-13", None)
        from_name.assert_called_once_with("pic", "run_cluster")

    async def test_reraises_connection_error_after_retries(self) -> None:
        from pic.models.db import JobType
        from pic.services.modal_dispatch import spawn_modal_job

        fn = MagicMock()
        fn.spawn.side_effect = ConnectionError("modal down")
        with (
            patch("pic.services.modal_dispatch._get_modal_function", return_value=fn),
            patch("asyncio.sleep", new_callable=AsyncMock),  # skip tenacity's async backoff
            pytest.raises(ConnectionError),
        ):
            await spawn_modal_job(JobType.PIPELINE, "job-x", None)
        assert fn.spawn.call_count == 3
