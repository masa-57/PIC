"""Unit tests for the GDrive sync worker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pic.services.gdrive import GDriveFile


def _make_gfile(name: str = "product.jpg", file_id: str = "f1", size: int = 1024) -> GDriveFile:
    return GDriveFile(id=file_id, name=name, mime_type="image/jpeg", size=size, parent_id="parent1")


def _fake_image_bytes(content: str = "image-data") -> bytes:
    """Create fake image bytes that produce a known hash."""
    return content.encode()


def _mock_db_for_batch() -> AsyncMock:
    """Create a mock DB session that handles dedup check (no match) + INSERT (success)."""
    mock_db = AsyncMock()
    mock_no_match = MagicMock()
    mock_no_match.scalar_one_or_none.return_value = None
    mock_insert = MagicMock()
    mock_insert.rowcount = 1

    # Use a callable side_effect so it doesn't run out
    call_count = 0

    async def execute_side_effect(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        # Odd calls are dedup checks, even calls are inserts (roughly)
        if call_count % 2 == 1:
            return mock_no_match
        return mock_insert

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    return mock_db


@pytest.mark.unit
class TestGdriveSyncWorker:
    @pytest.mark.asyncio
    async def test_sync_full_flow(self) -> None:
        """Full flow: download, process, upload, cluster."""
        gfile = _make_gfile()
        file_bytes = _fake_image_bytes("test-image")

        mock_db = _mock_db_for_batch()

        with (
            patch("pic.worker.gdrive_sync.build_drive_service"),
            patch("pic.worker.gdrive_sync.list_image_files", return_value=[gfile]),
            patch("pic.worker.gdrive_sync.get_or_create_processed_folder", return_value="proc-folder"),
            patch("pic.worker.gdrive_download.download_file", return_value=file_bytes),
            patch("pic.worker.gdrive_download.compute_embeddings_batch", return_value=[[0.1] * 768]),
            patch("pic.worker.gdrive_download.compute_hashes", return_value=("a" * 64, "b" * 64)),
            patch("pic.worker.gdrive_download.get_image_dimensions", return_value=(800, 600)),
            patch("pic.worker.gdrive_download.upload_to_s3") as mock_upload,
            patch("pic.worker.gdrive_download.generate_thumbnail", return_value=b"thumb"),
            patch("pic.worker.gdrive_download.move_file_to_folder") as mock_move,
            patch("pic.worker.gdrive_sync.run_full_clustering") as mock_cluster,
            patch("pic.worker.gdrive_sync.mark_job_completed") as mock_complete,
            patch("pic.worker.gdrive_sync.settings") as mock_settings,
        ):
            mock_settings.gdrive_service_account_json = '{"type":"service_account"}'
            mock_settings.gdrive_folder_id = "folder-123"
            mock_settings.max_image_download_mb = 50
            mock_settings.embedding_batch_size = 8
            mock_cluster.return_value = {"total_images": 1, "l1_groups": 1, "l2_clusters": 0, "l2_noise_groups": 1}

            from pic.worker.gdrive_sync import _sync_process_and_cluster

            await _sync_process_and_cluster(mock_db, "job-1", {})

        # Verify: uploaded original + thumbnail
        assert mock_upload.call_count == 2
        # Verify: moved file in GDrive
        mock_move.assert_called_once()
        # Verify: clustering was called
        mock_cluster.assert_called_once()
        # Verify: job completed with stats
        mock_complete.assert_called_once()
        result_dict = mock_complete.call_args[0][2]
        assert result_dict["files_discovered"] == 1
        assert result_dict["files_uploaded"] == 1
        assert result_dict["duplicates_skipped"] == 0

    @pytest.mark.asyncio
    async def test_sync_no_files_completes_without_clustering(self) -> None:
        """If no files found, job completes immediately without clustering."""
        mock_db = AsyncMock()

        with (
            patch("pic.worker.gdrive_sync.build_drive_service"),
            patch("pic.worker.gdrive_sync.list_image_files", return_value=[]),
            patch("pic.worker.gdrive_sync.run_full_clustering") as mock_cluster,
            patch("pic.worker.gdrive_sync.mark_job_completed") as mock_complete,
            patch("pic.worker.gdrive_sync.settings") as mock_settings,
        ):
            mock_settings.gdrive_service_account_json = '{"type":"service_account"}'
            mock_settings.gdrive_folder_id = "folder-123"

            from pic.worker.gdrive_sync import _sync_process_and_cluster

            await _sync_process_and_cluster(mock_db, "job-1", {})

        mock_cluster.assert_not_called()
        mock_complete.assert_called_once()
        result_dict = mock_complete.call_args[0][2]
        assert result_dict["files_discovered"] == 0
        assert result_dict["files_uploaded"] == 0

    @pytest.mark.asyncio
    async def test_sync_acquires_advisory_lock(self) -> None:
        """Worker acquires advisory lock before processing."""
        with (
            patch("pic.worker.helpers.async_session") as mock_session_ctx,
            patch("pic.worker.helpers.acquire_advisory_lock", return_value=True) as mock_lock,
            patch("pic.worker.helpers.mark_job_running"),
            patch("pic.worker.gdrive_sync._sync_process_and_cluster"),
            patch("pic.worker.helpers.release_advisory_lock"),
        ):
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from pic.worker.gdrive_sync import run_gdrive_sync

            await run_gdrive_sync("job-1")

        mock_lock.assert_called_once_with(mock_db, 0x4E494301, "job-1")

    @pytest.mark.asyncio
    async def test_sync_concurrent_lock_fails(self) -> None:
        """If advisory lock is not acquired, worker returns early without processing."""
        with (
            patch("pic.worker.helpers.async_session") as mock_session_ctx,
            patch("pic.worker.helpers.acquire_advisory_lock", return_value=False) as mock_lock,
            patch("pic.worker.gdrive_sync._sync_process_and_cluster") as mock_sync,
        ):
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from pic.worker.gdrive_sync import run_gdrive_sync

            await run_gdrive_sync("job-1")

        mock_lock.assert_called_once()
        mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_marks_job_failed_on_processing_exception(self) -> None:
        """Unhandled processing errors should mark job failed and release advisory lock."""
        with (
            patch("pic.worker.helpers.async_session") as mock_session_ctx,
            patch("pic.worker.helpers.acquire_advisory_lock", return_value=True),
            patch("pic.worker.helpers.mark_job_running"),
            patch("pic.worker.gdrive_sync._sync_process_and_cluster", side_effect=RuntimeError("boom")),
            patch("pic.worker.helpers.mark_job_failed") as mock_failed,
            patch("pic.worker.helpers.release_advisory_lock") as mock_release,
        ):
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            from pic.worker.gdrive_sync import run_gdrive_sync

            with pytest.raises(RuntimeError, match="boom"):
                await run_gdrive_sync("job-1")

        mock_db.rollback.assert_awaited_once()
        mock_failed.assert_awaited_once()
        failed_args = mock_failed.await_args.args
        assert failed_args[1] == "job-1"
        assert "boom" in failed_args[2]
        mock_release.assert_awaited_once_with(mock_db, 0x4E494301)

    @pytest.mark.asyncio
    async def test_sync_skips_oversized_files(self) -> None:
        """Files exceeding max_image_download_mb are skipped."""
        gfile = _make_gfile()
        large_bytes = b"x" * (51 * 1024 * 1024)  # 51MB

        mock_db = AsyncMock()

        with (
            patch("pic.worker.gdrive_download.download_file", return_value=large_bytes),
            patch("pic.worker.gdrive_download.move_file_to_folder"),
            patch("pic.worker.gdrive_download.compute_embeddings_batch") as mock_embed,
        ):
            from pic.worker.gdrive_download import process_batch

            result = await process_batch(
                mock_db,
                MagicMock(),
                [gfile],
                "proc-folder",
                50 * 1024 * 1024,
            )

        assert result["errored"] == 1
        assert result["uploaded"] == 0
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_skips_duplicate_content_hash(self) -> None:
        """Files with existing content_hash in DB are marked as duplicates."""
        gfile = _make_gfile()
        file_bytes = _fake_image_bytes("duplicate-image")

        mock_db = AsyncMock()
        mock_existing = MagicMock()
        mock_existing.scalar_one_or_none.return_value = "existing-image-id"
        mock_db.execute.return_value = mock_existing

        with (
            patch("pic.worker.gdrive_download.download_file", return_value=file_bytes),
            patch("pic.worker.gdrive_download.move_file_to_folder"),
            patch("pic.worker.gdrive_download.compute_embeddings_batch") as mock_embed,
        ):
            from pic.worker.gdrive_download import process_batch

            result = await process_batch(
                mock_db,
                MagicMock(),
                [gfile],
                "proc-folder",
                50 * 1024 * 1024,
            )

        assert result["duplicates"] == 1
        assert result["uploaded"] == 0
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_continues_on_individual_failure(self) -> None:
        """Individual file failure doesn't abort the batch."""
        gfile1 = _make_gfile(name="good.jpg", file_id="f1")
        gfile2 = _make_gfile(name="bad.jpg", file_id="f2")

        good_bytes = _fake_image_bytes("good-image")
        bad_bytes = _fake_image_bytes("bad-image")

        mock_db = AsyncMock()
        # Both pass dedup check
        mock_no_match = MagicMock()
        mock_no_match.scalar_one_or_none.return_value = None
        # INSERT succeeds for first, fails for second
        mock_insert_ok = MagicMock()
        mock_insert_ok.rowcount = 1
        mock_db.execute.side_effect = [mock_no_match, mock_no_match, mock_insert_ok, Exception("DB error")]

        def side_download(svc: object, fid: str) -> bytes:
            return good_bytes if fid == "f1" else bad_bytes

        with (
            patch("pic.worker.gdrive_download.download_file", side_effect=side_download),
            patch("pic.worker.gdrive_download.compute_embeddings_batch", return_value=[[0.1] * 768, [0.2] * 768]),
            patch("pic.worker.gdrive_download.compute_hashes", return_value=("a" * 64, "b" * 64)),
            patch("pic.worker.gdrive_download.get_image_dimensions", return_value=(100, 100)),
            patch("pic.worker.gdrive_download.upload_to_s3"),
            patch("pic.worker.gdrive_download.generate_thumbnail", return_value=b"thumb"),
            patch("pic.worker.gdrive_download.move_file_to_folder"),
        ):
            from pic.worker.gdrive_download import process_batch

            result = await process_batch(
                mock_db,
                MagicMock(),
                [gfile1, gfile2],
                "proc-folder",
                50 * 1024 * 1024,
            )

        assert result["uploaded"] == 1
        assert result["errored"] == 1

    @pytest.mark.asyncio
    async def test_sync_download_failure_skips_file_and_increments_errored(self) -> None:
        """Download failure from GDrive should skip the file and increment errored count."""
        gfile = _make_gfile()
        mock_db = AsyncMock()

        with (
            patch("pic.worker.gdrive_download.download_file", side_effect=ConnectionError("GDrive unreachable")),
            patch("pic.worker.gdrive_download.compute_embeddings_batch") as mock_embed,
        ):
            from pic.worker.gdrive_download import process_batch

            result = await process_batch(
                mock_db,
                MagicMock(),
                [gfile],
                "proc-folder",
                50 * 1024 * 1024,
            )

        assert result["errored"] == 1
        assert result["uploaded"] == 0
        assert result["duplicates"] == 0
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_batch_embedding_failure_marks_all_as_errored(self) -> None:
        """When batch embedding fails, all files in the batch are marked as errored."""
        gfile1 = _make_gfile(name="a.jpg", file_id="f1")
        gfile2 = _make_gfile(name="b.jpg", file_id="f2")

        mock_db = AsyncMock()
        mock_no_match = MagicMock()
        mock_no_match.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_no_match)

        with (
            patch("pic.worker.gdrive_download.download_file", return_value=_fake_image_bytes("img")),
            patch("pic.worker.gdrive_download.compute_embeddings_batch", side_effect=RuntimeError("GPU OOM")),
            patch("pic.worker.gdrive_download.move_file_to_folder"),
        ):
            from pic.worker.gdrive_download import process_batch

            result = await process_batch(
                mock_db,
                MagicMock(),
                [gfile1, gfile2],
                "proc-folder",
                50 * 1024 * 1024,
            )

        assert result["errored"] == 2
        assert result["uploaded"] == 0

    @pytest.mark.asyncio
    async def test_sync_marks_job_completed_with_stats(self) -> None:
        """Job is marked completed with correct summary stats."""
        gfile = _make_gfile()
        file_bytes = _fake_image_bytes("test")

        mock_db = _mock_db_for_batch()

        with (
            patch("pic.worker.gdrive_sync.build_drive_service"),
            patch("pic.worker.gdrive_sync.list_image_files", return_value=[gfile]),
            patch("pic.worker.gdrive_sync.get_or_create_processed_folder", return_value="proc"),
            patch("pic.worker.gdrive_download.download_file", return_value=file_bytes),
            patch("pic.worker.gdrive_download.compute_embeddings_batch", return_value=[[0.1] * 768]),
            patch("pic.worker.gdrive_download.compute_hashes", return_value=("a" * 64, "b" * 64)),
            patch("pic.worker.gdrive_download.get_image_dimensions", return_value=(100, 100)),
            patch("pic.worker.gdrive_download.upload_to_s3"),
            patch("pic.worker.gdrive_download.generate_thumbnail", return_value=b"t"),
            patch("pic.worker.gdrive_download.move_file_to_folder"),
            patch("pic.worker.gdrive_sync.run_full_clustering") as mock_cluster,
            patch("pic.worker.gdrive_sync.mark_job_completed") as mock_complete,
            patch("pic.worker.gdrive_sync.settings") as mock_settings,
        ):
            mock_settings.gdrive_service_account_json = '{"type":"service_account"}'
            mock_settings.gdrive_folder_id = "folder-123"
            mock_settings.max_image_download_mb = 50
            mock_settings.embedding_batch_size = 8
            mock_cluster.return_value = {"total_images": 1, "l1_groups": 1, "l2_clusters": 0, "l2_noise_groups": 0}

            from pic.worker.gdrive_sync import _sync_process_and_cluster

            await _sync_process_and_cluster(mock_db, "job-1", {})

        mock_complete.assert_called_once()
        stats = mock_complete.call_args[0][2]
        assert stats["files_discovered"] == 1
        assert stats["files_uploaded"] == 1
        assert stats["duplicates_skipped"] == 0
        assert stats["files_errored"] == 0
        assert stats["total_bytes"] == len(file_bytes)
        assert stats["l1_groups"] == 1
