"""Unit tests for the pipeline worker and API."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestListS3Objects:
    def test_lists_objects_single_page(self, mock_s3):
        from pic.services.image_store import list_s3_objects

        mock_s3.list_objects.return_value = ["images/a.jpg", "images/b.png"]

        keys = list_s3_objects("images/")
        assert keys == ["images/a.jpg", "images/b.png"]
        mock_s3.list_objects.assert_called_once_with("images/")

    def test_handles_pagination(self, mock_s3):
        """Pagination is now handled internally by the storage backend."""
        from pic.services.image_store import list_s3_objects

        mock_s3.list_objects.return_value = ["images/a.jpg", "images/b.jpg"]

        keys = list_s3_objects("images/")
        assert keys == ["images/a.jpg", "images/b.jpg"]
        mock_s3.list_objects.assert_called_once_with("images/")

    def test_empty_bucket(self, mock_s3):
        from pic.services.image_store import list_s3_objects

        mock_s3.list_objects.return_value = []

        keys = list_s3_objects("images/")
        assert keys == []


@pytest.mark.unit
class TestDeleteS3Object:
    def test_deletes_object(self, mock_s3):
        from pic.services.image_store import delete_s3_object

        delete_s3_object("images/photo.jpg")

        mock_s3.delete.assert_called_once_with("images/photo.jpg")


@pytest.mark.unit
class TestPipelineDedup:
    def test_sha256_content_hash_consistency(self):
        """Same bytes should produce same hash."""
        data = b"identical image content"
        hash1 = hashlib.sha256(data).hexdigest()
        hash2 = hashlib.sha256(data).hexdigest()
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_sha256_different_content(self):
        """Different bytes should produce different hash."""
        hash1 = hashlib.sha256(b"image A").hexdigest()
        hash2 = hashlib.sha256(b"image B").hexdigest()
        assert hash1 != hash2


@pytest.mark.unit
class TestPipelineDiscoverAndDedup:
    @pytest.mark.asyncio
    async def test_skips_duplicate_in_db(self):
        """Images with matching content_hash in DB should be moved to rejected/."""
        content = b"duplicate-image-bytes"

        mock_session = AsyncMock()
        # First call: key-based pre-download dedup query → no key match.
        mock_existing_key_result = MagicMock()
        mock_existing_key_result.scalars.return_value.all.return_value = []

        # Second call: select Image.id where content_hash matches → returns existing.
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = "existing-image-id"
        mock_session.execute = AsyncMock(side_effect=[mock_existing_key_result, mock_existing_result])

        with (
            patch("pic.worker.pipeline_discover.list_s3_objects", return_value=["images/dup.jpg"]),
            patch("pic.worker.pipeline_discover.download_from_s3", return_value=content),
            patch("pic.worker.pipeline_discover.move_s3_object") as mock_move,
        ):
            from pic.worker.pipeline_discover import phase_discover_and_dedup

            new_ids, stats = await phase_discover_and_dedup(mock_session, "job-1")

        assert new_ids == []
        assert stats["duplicates"] == 1
        mock_move.assert_called_once_with("images/dup.jpg", "rejected/dup.jpg")

    @pytest.mark.asyncio
    async def test_skips_intra_batch_duplicate(self):
        """Two identical files in the same batch should result in one kept, one rejected."""
        content = b"same-image-bytes"

        mock_session = AsyncMock()
        mock_session.add = MagicMock()  # db.add() is synchronous in SQLAlchemy
        # Pre-download key dedup: no matches.
        mock_key_result = MagicMock()
        mock_key_result.scalars.return_value.all.return_value = []

        # For content-hash duplicate check: return None (not in DB).
        mock_no_match = MagicMock()
        mock_no_match.scalar_one_or_none.return_value = None
        mock_insert = MagicMock()
        mock_insert.rowcount = 1
        mock_session.execute = AsyncMock(side_effect=[mock_key_result, mock_no_match, mock_insert])

        with (
            patch(
                "pic.worker.pipeline_discover.list_s3_objects",
                return_value=["images/a.jpg", "images/b.jpg"],
            ),
            patch("pic.worker.pipeline_discover.download_from_s3", return_value=content),
            patch("pic.worker.pipeline_discover.move_s3_object") as mock_move,
        ):
            from pic.worker.pipeline_discover import phase_discover_and_dedup

            new_ids, stats = await phase_discover_and_dedup(mock_session, "job-1")

        # First file is kept, second is a duplicate
        assert len(new_ids) == 1
        assert stats["duplicates"] == 1
        mock_move.assert_called_once_with("images/b.jpg", "rejected/b.jpg")

    @pytest.mark.asyncio
    async def test_skips_existing_processed_key_before_download(self):
        """If processed/<name> already exists in DB, skip download for images/<name>."""
        content = b"new-image-bytes"
        mock_session = AsyncMock()

        mock_key_result = MagicMock()
        mock_key_result.scalars.return_value.all.return_value = ["processed/existing.jpg"]

        mock_no_match = MagicMock()
        mock_no_match.scalar_one_or_none.return_value = None

        mock_insert = MagicMock()
        mock_insert.rowcount = 1

        mock_session.execute = AsyncMock(side_effect=[mock_key_result, mock_no_match, mock_insert])

        with (
            patch(
                "pic.worker.pipeline_discover.list_s3_objects",
                return_value=["images/existing.jpg", "images/new.jpg"],
            ),
            patch("pic.worker.pipeline_discover.download_from_s3", return_value=content) as mock_download,
            patch("pic.worker.pipeline_discover.move_s3_object") as mock_move,
        ):
            from pic.worker.pipeline_discover import phase_discover_and_dedup

            new_ids, stats = await phase_discover_and_dedup(mock_session, "job-1")

        assert len(new_ids) == 1
        assert stats["discovered"] == 2
        assert stats["duplicates"] == 1
        mock_download.assert_called_once_with("images/new.jpg")
        mock_move.assert_called_once_with("images/existing.jpg", "rejected/existing.jpg")

    @pytest.mark.asyncio
    async def test_filters_non_image_files(self):
        """Non-image files (e.g. .txt, .json) should be ignored."""
        mock_session = AsyncMock()

        with (
            patch(
                "pic.worker.pipeline_discover.list_s3_objects",
                return_value=["images/readme.txt", "images/data.json"],
            ),
        ):
            from pic.worker.pipeline_discover import phase_discover_and_dedup

            new_ids, stats = await phase_discover_and_dedup(mock_session, "job-1")

        assert new_ids == []
        assert stats["discovered"] == 0


@pytest.mark.unit
class TestPipelineConcurrentDownload:
    @pytest.mark.asyncio
    async def test_download_s3_concurrent_preserves_order_and_marks_failures(self):
        def side_download(s3_key: str) -> bytes:
            if s3_key == "images/b.jpg":
                raise RuntimeError("download failed")
            return s3_key.encode()

        with patch("pic.worker.pipeline_discover.download_from_s3", side_effect=side_download):
            from pic.worker.pipeline_discover import download_s3_concurrent

            results = await download_s3_concurrent(
                ["images/a.jpg", "images/b.jpg", "images/c.jpg"],
                max_concurrency=2,
            )

        assert results == [
            ("images/a.jpg", b"images/a.jpg"),
            ("images/b.jpg", None),
            ("images/c.jpg", b"images/c.jpg"),
        ]


@pytest.mark.unit
class TestPipelineIngestRetry:
    @pytest.mark.asyncio
    async def test_batch_embedding_failure_retries_per_image(self):
        mock_db = AsyncMock()
        image = MagicMock()
        image.id = "img-1"
        image.s3_key = "images/a.jpg"

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [image]
        # First execute returns selected images; second is progress update.
        mock_db.execute = AsyncMock(side_effect=[select_result, MagicMock()])

        # Batch call fails, then single-image retry succeeds
        batch_embed = MagicMock(side_effect=Exception("batch embedding failed"))
        retry_embed = MagicMock(return_value=[[0.1] * 768])

        with (
            patch("pic.worker.pipeline_discover.download_from_s3", return_value=b"image-bytes"),
            patch("pic.worker.pipeline_ingest.compute_embeddings_batch", batch_embed),
            patch("pic.worker.image_processing.compute_embeddings_batch", retry_embed),
            patch("pic.worker.image_processing.process_single_image", return_value=True) as mock_process,
        ):
            from pic.worker.pipeline_ingest import phase_batch_ingest

            stats = await phase_batch_ingest(mock_db, "job-1", ["img-1"])

        assert stats["ingested"] == 1
        assert stats["retried_success_count"] == 1
        assert stats["failed_image_ids"] == []
        # Verify retry path: batch embed failed once, retry embed succeeded once
        batch_embed.assert_called_once()
        retry_embed.assert_called_once()
        # process_single_image is called by retry_single_image_ingest after re-embedding
        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_embedding_failure_retry_exhaustion_records_failed_ids(self):
        mock_db = AsyncMock()
        image = MagicMock()
        image.id = "img-1"
        image.s3_key = "images/a.jpg"

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [image]
        mock_db.execute = AsyncMock(return_value=select_result)

        # All calls fail (batch + 2 retries)
        embed_mock = MagicMock(side_effect=Exception("embedding failed"))

        with (
            patch("pic.worker.pipeline_discover.download_from_s3", return_value=b"image-bytes"),
            patch("pic.worker.pipeline_ingest.compute_embeddings_batch", embed_mock),
            patch("pic.worker.image_processing.compute_embeddings_batch", embed_mock),
            patch("pic.worker.image_processing.process_single_image") as mock_process,
        ):
            from pic.worker.pipeline_ingest import phase_batch_ingest

            stats = await phase_batch_ingest(mock_db, "job-1", ["img-1"])

        assert stats["ingested"] == 0
        assert stats["retried_success_count"] == 0
        assert stats["failed_image_ids"] == ["img-1"]
        assert stats["skipped_download_image_ids"] == []
        assert embed_mock.call_count == 3  # one batch attempt + two retry attempts
        # process_single_image never called because embedding always fails
        mock_process.assert_not_called()
