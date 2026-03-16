"""Unit tests for API key authentication."""

import logging
from unittest.mock import patch

import pytest
from fastapi import HTTPException


@pytest.mark.unit
class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_valid_key_passes(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from pic.core.auth import verify_api_key

            await verify_api_key("correct-key")

    @pytest.mark.asyncio
    async def test_invalid_key_raises_401(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from pic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key("wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_none_key_raises_401(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from pic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_string_key_raises_401(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "correct-key"
            from pic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key("")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_configured_key_skips_auth(self):
        """Explicit auth disable should bypass API-key checks."""
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.env = "development"
            mock_settings.auth_disabled = True
            from pic.core.auth import verify_api_key

            await verify_api_key(None)
            await verify_api_key("")
            await verify_api_key("any-random-key")

    @pytest.mark.asyncio
    async def test_no_key_in_development_raises_503_without_explicit_disable(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.env = "development"
            mock_settings.auth_disabled = False
            from pic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_no_key_in_staging_raises_503_without_explicit_disable(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.env = "staging"
            mock_settings.auth_disabled = False
            from pic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_no_key_in_production_raises_503(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.env = "production"
            mock_settings.auth_disabled = False
            from pic.core.auth import verify_api_key

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(None)
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_timing_safe_comparison(self):
        """Ensure hmac.compare_digest is used (not plain ==)."""
        import hmac

        with (
            patch("pic.core.auth.settings") as mock_settings,
            patch("pic.core.auth.hmac.compare_digest", wraps=hmac.compare_digest) as mock_compare,
        ):
            mock_settings.api_key = "test-key"
            from pic.core.auth import verify_api_key

            await verify_api_key("test-key")
            mock_compare.assert_called_once_with("test-key", "test-key")


@pytest.mark.unit
class TestAuthModeLogging:
    def test_log_auth_mode_enabled(self, caplog):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret"
            mock_settings.env = "staging"
            mock_settings.auth_disabled = False
            from pic.core.auth import log_auth_mode

            with caplog.at_level(logging.INFO):
                log_auth_mode()

        assert "Authentication enabled with PIC_API_KEY" in caplog.text

    def test_log_auth_mode_explicitly_disabled(self, caplog):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.env = "development"
            mock_settings.auth_disabled = True
            from pic.core.auth import log_auth_mode

            with caplog.at_level(logging.WARNING):
                log_auth_mode()

        assert "Authentication disabled explicitly" in caplog.text

    def test_log_auth_mode_misconfigured(self, caplog):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = ""
            mock_settings.env = "staging"
            mock_settings.auth_disabled = False
            from pic.core.auth import log_auth_mode

            with caplog.at_level(logging.ERROR):
                log_auth_mode()

        assert "Protected endpoints will return 503" in caplog.text
