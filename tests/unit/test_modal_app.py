"""Unit tests for modal_app helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_has_inflight_gdrive_sync_job_true() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 2
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("pic.core.database.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from pic.modal_app import _has_inflight_gdrive_sync_job

        assert await _has_inflight_gdrive_sync_job() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_has_inflight_gdrive_sync_job_false() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 0
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("pic.core.database.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from pic.modal_app import _has_inflight_gdrive_sync_job

        assert await _has_inflight_gdrive_sync_job() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_gdrive_skips_spawn_when_job_already_inflight() -> None:
    with (
        patch("pic.config.settings") as mock_settings,
        patch("pic.services.gdrive.build_drive_service", return_value=MagicMock()),
        patch("pic.services.gdrive.list_image_files", return_value=[MagicMock(id="f1")]),
        patch("pic.modal_app._has_inflight_gdrive_sync_job", new_callable=AsyncMock, return_value=True),
        patch("pic.modal_app.modal.Function.from_name") as mock_from_name,
    ):
        mock_settings.gdrive_folder_id = "folder-123"
        mock_settings.gdrive_service_account_json = '{"type":"service_account"}'

        from pic.modal_app import _check_gdrive_for_new_files_impl

        await _check_gdrive_for_new_files_impl()

    mock_from_name.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_gdrive_spawns_worker_when_files_present_and_no_inflight_job() -> None:
    mock_fn = MagicMock()

    with (
        patch("pic.config.settings") as mock_settings,
        patch("pic.services.gdrive.build_drive_service", return_value=MagicMock()),
        patch("pic.services.gdrive.list_image_files", return_value=[MagicMock(id="f1")]),
        patch("pic.modal_app._has_inflight_gdrive_sync_job", new_callable=AsyncMock, return_value=False),
        patch("pic.modal_app.modal.Function.from_name", return_value=mock_fn) as mock_from_name,
    ):
        mock_settings.gdrive_folder_id = "folder-123"
        mock_settings.gdrive_service_account_json = '{"type":"service_account"}'

        from pic.modal_app import _check_gdrive_for_new_files_impl

        await _check_gdrive_for_new_files_impl()

    mock_from_name.assert_called_once_with("nic", "sync_gdrive_to_r2")
    mock_fn.spawn.assert_called_once()
