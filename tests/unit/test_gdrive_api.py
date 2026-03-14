"""Unit tests for the GDrive sync API endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pic.api.gdrive import router


def _build_app() -> FastAPI:
    """Create a minimal FastAPI app with only the GDrive router for testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.unit
class TestGdriveApi:
    @pytest.mark.asyncio
    async def test_trigger_sync_returns_202(self) -> None:
        """POST /gdrive/sync returns 202 with a job when configured."""
        app = _build_app()

        mock_job = AsyncMock()
        mock_job.id = "job-123"
        mock_job.type = "gdrive_sync"
        mock_job.status = "pending"
        mock_job.progress = 0.0
        mock_job.result = None
        mock_job.error = None
        mock_job.created_at = "2026-02-13T10:00:00Z"
        mock_job.completed_at = None

        with (
            patch("pic.api.gdrive.settings") as mock_settings,
            patch("pic.api.gdrive.create_and_dispatch_job", return_value=mock_job),
            patch("pic.api.gdrive.get_db"),
        ):
            mock_settings.gdrive_folder_id = "folder-123"
            mock_settings.gdrive_service_account_json = '{"type":"service_account"}'

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/v1/gdrive/sync")

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_trigger_sync_not_configured_returns_400(self) -> None:
        """POST /gdrive/sync returns 400 when GDrive is not configured."""
        app = _build_app()

        with (
            patch("pic.api.gdrive.settings") as mock_settings,
            patch("pic.api.gdrive.get_db"),
        ):
            mock_settings.gdrive_folder_id = ""
            mock_settings.gdrive_service_account_json = ""

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/v1/gdrive/sync")

        assert response.status_code == 400
        assert "not configured" in response.json()["detail"]
