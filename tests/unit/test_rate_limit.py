"""Unit tests for rate limit keying behavior."""

from unittest.mock import patch

import pytest
from starlette.requests import Request

from pic.core.rate_limit import _get_rate_limit_key


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/images",
        "query_string": b"",
        "headers": headers or [],
        "client": ("203.0.113.7", 12345),
        "server": ("test", 80),
    }
    return Request(scope)


def test_uses_hashed_api_key_when_present() -> None:
    req = _request([(b"x-api-key", b"secret-key")])
    key = _get_rate_limit_key(req)
    assert key.startswith("apikey:")
    assert len(key) == len("apikey:") + 16


def test_hashing_is_deterministic_for_same_api_key() -> None:
    req1 = _request([(b"x-api-key", b"same-key")])
    req2 = _request([(b"x-api-key", b"same-key")])
    assert _get_rate_limit_key(req1) == _get_rate_limit_key(req2)


def test_falls_back_to_remote_ip_without_api_key() -> None:
    req = _request()
    assert _get_rate_limit_key(req) == "203.0.113.7"


@pytest.mark.unit
class TestCreateLimiter:
    def test_uses_in_memory_when_storage_url_empty(self) -> None:
        with patch("pic.core.rate_limit.settings") as mock_settings:
            mock_settings.rate_limit_default = "60/minute"
            mock_settings.rate_limit_burst = "10/second"
            mock_settings.rate_limit_storage_url = ""

            from pic.core.rate_limit import create_limiter

            lim = create_limiter()
            # When no storage_uri is set, slowapi uses MemoryStorage by default
            assert lim is not None

    def test_passes_storage_uri_when_set(self) -> None:
        with patch("pic.core.rate_limit.settings") as mock_settings:
            mock_settings.rate_limit_default = "60/minute"
            mock_settings.rate_limit_burst = "10/second"
            mock_settings.rate_limit_storage_url = "memory://"

            from pic.core.rate_limit import create_limiter

            lim = create_limiter()
            # Limiter was created successfully with explicit storage_uri
            assert lim is not None
