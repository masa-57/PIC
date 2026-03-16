"""Unit tests for URL ingest worker."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestDownloadFromUrl:
    @pytest.mark.asyncio
    async def test_downloads_valid_image_url(self):
        from pic.worker.url_ingest import download_from_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg", "content-length": "1024"}
        mock_response.content = b"fake-image-data"
        mock_response.raise_for_status = MagicMock()

        with patch("pic.worker.url_ingest.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await download_from_url("https://example.com/photo.jpg")
            assert result == b"fake-image-data"

    @pytest.mark.asyncio
    async def test_rejects_non_image_content_type(self):
        from pic.worker.url_ingest import download_from_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("pic.worker.url_ingest.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="not an image"):
                await download_from_url("https://example.com/page.html")

    @pytest.mark.asyncio
    async def test_rejects_oversized_response(self):
        from pic.worker.url_ingest import download_from_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg", "content-length": str(500 * 1024 * 1024)}
        mock_response.raise_for_status = MagicMock()

        with patch("pic.worker.url_ingest.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="exceeds size limit"):
                await download_from_url("https://example.com/huge.jpg")


@pytest.mark.unit
class TestRunUrlIngest:
    @pytest.mark.asyncio
    async def test_auto_pipeline_creates_separate_pipeline_job(self):
        from pic.models.db import JobType
        from pic.worker.url_ingest import DownloadResult, run_url_ingest

        running_db = AsyncMock()
        running_db.execute = AsyncMock(return_value=MagicMock())

        work_db = AsyncMock()
        work_db.execute = AsyncMock(return_value=MagicMock())
        work_db.add = MagicMock()

        with (
            patch("pic.core.database.async_session") as mock_session_factory,
            patch(
                "pic.worker.url_ingest._download_urls",
                new_callable=AsyncMock,
                return_value=[DownloadResult(url="https://example.com/photo.jpg", image_bytes=b"fake-image-data")],
            ),
            patch("pic.worker.image_processing.check_content_duplicate", new_callable=AsyncMock, return_value=False),
            patch("pic.worker.image_processing.insert_image_record", new_callable=AsyncMock, return_value="img-1"),
            patch("pic.services.image_store.upload_to_s3"),
            patch(
                "pic.services.modal_dispatch.submit_pipeline_job",
                new_callable=AsyncMock,
                return_value="call-123",
            ) as mock_submit_pipeline_job,
        ):
            mock_session_factory.return_value.__aenter__ = AsyncMock(side_effect=[running_db, work_db])
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await run_url_ingest("url-job-1", ["https://example.com/photo.jpg"], auto_pipeline=True)

        mock_submit_pipeline_job.assert_awaited_once()
        pipeline_job_id = mock_submit_pipeline_job.await_args.args[0]

        assert pipeline_job_id != "url-job-1"
        added_job = work_db.add.call_args.args[0]
        assert added_job.id == pipeline_job_id
        assert added_job.type == JobType.PIPELINE

        final_stmt = work_db.execute.await_args_list[-1].args[0]
        result_payload = json.loads(final_stmt.compile().params["result"])
        assert result_payload["pipeline_job_id"] == pipeline_job_id
        assert result_payload["new_image_ids"] == ["img-1"]
        assert result_payload["auto_pipeline_requested"] is True
