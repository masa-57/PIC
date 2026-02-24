"""Unit tests for database module — SSL/TLS context configuration."""

import ssl
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestBuildEngineArgs:
    """Test _build_engine_args SSL context creation."""

    def _call(self, url: str, db_ssl_ca: str = "") -> tuple[str, dict[str, object]]:
        """Import and call _build_engine_args with mocked settings."""
        with patch("pic.core.database.settings") as mock_settings:
            mock_settings.db_ssl_ca = db_ssl_ca
            mock_settings.db_pool_size = 5
            mock_settings.db_pool_max_overflow = 10
            mock_settings.db_pool_timeout = 30
            mock_settings.database_url = url
            # Re-import to get the function (but call it directly)
            from pic.core.database import _build_engine_args

            return _build_engine_args(url)

    def test_no_sslmode_localhost_no_ssl(self) -> None:
        clean_url, connect_args = self._call("postgresql+asyncpg://localhost:5432/pic")
        assert "ssl" not in connect_args
        assert "command_timeout" in connect_args

    def test_sslmode_require_localhost_disables_verification(self) -> None:
        clean_url, connect_args = self._call("postgresql+asyncpg://localhost:5432/pic?sslmode=require")
        ctx = connect_args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_sslmode_verify_full_enforces_verification(self) -> None:
        clean_url, connect_args = self._call("postgresql+asyncpg://db.neon.tech:5432/pic?sslmode=verify-full")
        ctx = connect_args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_sslmode_require_remote_uses_default_context(self) -> None:
        """Remote host with sslmode=require uses default SSL context (CERT_REQUIRED by default)."""
        clean_url, connect_args = self._call("postgresql+asyncpg://db.neon.tech:5432/pic?sslmode=require")
        ctx = connect_args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        # create_default_context sets CERT_REQUIRED and check_hostname=True by default
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_sslmode_disable_no_ssl(self) -> None:
        clean_url, connect_args = self._call("postgresql+asyncpg://db.neon.tech:5432/pic?sslmode=disable")
        assert "ssl" not in connect_args

    def test_no_sslmode_remote_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="pic.core.database"):
            self._call("postgresql+asyncpg://db.neon.tech:5432/pic")
        assert "sslmode=verify-full" in caplog.text

    def test_sslmode_stripped_from_url(self) -> None:
        clean_url, _ = self._call("postgresql+asyncpg://localhost:5432/pic?sslmode=require&application_name=test")
        assert "sslmode" not in clean_url
        assert "application_name=test" in clean_url
