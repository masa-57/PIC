"""Unit tests for middleware modules extracted from main.py."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with auth disabled."""
    with patch("pic.core.auth.settings") as mock_auth_settings:
        mock_auth_settings.api_key = ""
        from pic.main import app

        with TestClient(app) as c:
            yield c


@pytest.mark.unit
class TestSanitizeRequestId:
    def test_valid_id_is_preserved(self):
        from pic.core.middleware import _sanitize_request_id

        assert _sanitize_request_id("abc-123.def_456") == "abc-123.def_456"

    def test_none_generates_uuid(self):
        from pic.core.middleware import _sanitize_request_id

        result = _sanitize_request_id(None)
        assert len(result) == 36  # UUID4 format

    def test_empty_generates_uuid(self):
        from pic.core.middleware import _sanitize_request_id

        result = _sanitize_request_id("")
        assert len(result) == 36

    def test_newline_injection_rejected(self):
        from pic.core.middleware import _sanitize_request_id

        result = _sanitize_request_id("bad\nid")
        assert "\n" not in result
        assert len(result) == 36

    def test_too_long_id_rejected(self):
        from pic.core.middleware import _sanitize_request_id

        result = _sanitize_request_id("a" * 65)
        assert len(result) == 36

    def test_max_length_id_accepted(self):
        from pic.core.middleware import _sanitize_request_id

        long_id = "a" * 64
        assert _sanitize_request_id(long_id) == long_id


@pytest.mark.unit
class TestSecurityHeaders:
    def test_security_headers_on_api_response(self, client):
        with patch("pic.api.health.engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert "strict-origin-when-cross-origin" in response.headers["Referrer-Policy"]
            assert "Strict-Transport-Security" in response.headers


@pytest.mark.unit
class TestRequestSizeLimit:
    def test_rejects_large_content_length(self, client):
        # Default max is 20MB; send a Content-Length header exceeding that
        response = client.post(
            "/api/v1/jobs",
            headers={"Content-Length": str(100 * 1024 * 1024)},
            content=b"x",
        )
        assert response.status_code == 413
