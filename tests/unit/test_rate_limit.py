"""Unit tests for rate limit keying behavior."""

from starlette.requests import Request

from nic.core.rate_limit import _get_rate_limit_key


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
