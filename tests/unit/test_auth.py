"""Unit tests for API key authentication."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException


@pytest.mark.unit
class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_passes(self):
        with patch("nic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from nic.core.auth import verify_api_key

            await verify_api_key("correct-key")

    @pytest.mark.asyncio
    async def test_invalid_key_raises_401(self):
        with patch("nic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from nic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key("wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_none_key_raises_401(self):
        with patch("nic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from nic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_string_key_raises_401(self):
        with patch("nic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from nic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key("")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_configured_key_skips_auth(self):
        """When api_key is empty, all requests pass (dev mode)."""
        with patch("nic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            from nic.core.auth import verify_api_key

            await verify_api_key(None)
            await verify_api_key("")
            await verify_api_key("any-random-key")

    @pytest.mark.asyncio
    async def test_timing_safe_comparison(self):
        """Ensure hmac.compare_digest is used (not plain ==)."""
        import hmac

        with (
            patch("nic.core.auth.settings") as mock_settings,
            patch("nic.core.auth.hmac.compare_digest", wraps=hmac.compare_digest) as mock_compare,
        ):
            mock_settings.api_key = "test-key"
            from nic.core.auth import verify_api_key

            await verify_api_key("test-key")
            mock_compare.assert_called_once_with("test-key", "test-key")
