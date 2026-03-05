"""Unit tests for URL ingest worker."""

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
