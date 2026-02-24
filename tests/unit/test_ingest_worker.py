"""Unit tests for the ingest worker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestRunIngest:
    @pytest.mark.asyncio
    async def test_moves_to_processed_after_success(self, sample_embedding, sample_phash):
        """After computing embedding, image should be moved to processed/ prefix."""
        mock_image = MagicMock()
        mock_image.id = "abc-123"
        mock_image.s3_key = "images/photo.jpg"
        mock_image.phash = None
        mock_image.dhash = None
        mock_image.embedding = None
        mock_image.has_embedding = 0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_image

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("nic.worker.ingest.async_session", return_value=mock_session_ctx),
            patch("nic.worker.ingest.download_from_s3", return_value=b"fake-image-bytes"),
            patch("nic.worker.ingest.compute_hashes", return_value=(sample_phash, sample_phash)),
            patch("nic.worker.ingest.compute_embedding", return_value=sample_embedding),
            patch("nic.worker.ingest.move_s3_object") as mock_move,
        ):
            from nic.worker.ingest import run_ingest

            await run_ingest("abc-123")

        mock_move.assert_called_once_with("images/photo.jpg", "processed/photo.jpg")
        assert mock_image.s3_key == "processed/photo.jpg"
        assert mock_image.phash_bits is not None

    @pytest.mark.asyncio
    async def test_move_failure_does_not_fail_ingest(self, sample_embedding, sample_phash):
        """If S3 move fails, ingest should still succeed (embedding is saved)."""
        mock_image = MagicMock()
        mock_image.id = "abc-123"
        mock_image.s3_key = "images/photo.jpg"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_image

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("nic.worker.ingest.async_session", return_value=mock_session_ctx),
            patch("nic.worker.ingest.download_from_s3", return_value=b"fake-image-bytes"),
            patch("nic.worker.ingest.compute_hashes", return_value=(sample_phash, sample_phash)),
            patch("nic.worker.ingest.compute_embedding", return_value=sample_embedding),
            patch("nic.worker.ingest.move_s3_object", side_effect=Exception("S3 error")),
        ):
            from nic.worker.ingest import run_ingest

            await run_ingest("abc-123")

        assert mock_image.has_embedding == 1
        # s3_key should remain the original since move failed
        assert mock_image.s3_key == "images/photo.jpg"
