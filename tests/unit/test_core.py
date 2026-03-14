"""Unit tests for core infrastructure (TC-1): logging, request ID middleware, health."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

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
class TestSetupLogging:
    def test_json_format_produces_json(self):
        from pic.core.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_json_format_includes_exception(self):
        from pic.core.logging import JSONFormatter

        formatter = JSONFormatter()
        try:
            raise ValueError("test error")  # noqa: TRY301
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]

    def test_json_format_includes_request_id(self):
        from pic.core.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-abc-123"  # type: ignore[attr-defined]
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "req-abc-123"

    def test_setup_logging_configures_handler(self):
        from pic.core.logging import setup_logging

        setup_logging(level=logging.DEBUG, json_format=False)
        root = logging.getLogger()
        assert root.level == logging.DEBUG


@pytest.mark.unit
class TestRequestIdMiddleware:
    def test_generates_request_id(self, client):
        with patch("pic.api.health.engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health")
            assert "X-Request-ID" in response.headers

    def test_preserves_provided_request_id(self, client):
        with patch("pic.api.health.engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health", headers={"X-Request-ID": "my-custom-id"})
            assert response.headers["X-Request-ID"] == "my-custom-id"

    def test_rejects_unsafe_request_id(self, client):
        with patch("pic.api.health.engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health", headers={"X-Request-ID": "bad\nid"})
            assert response.headers["X-Request-ID"] != "bad\nid"


@pytest.mark.unit
class TestDetailedHealthEndpoint:
    def test_detailed_health_ok(self, client):
        with (
            patch("pic.api.health.engine") as mock_engine,
            patch("pic.api.health.async_session") as mock_session_factory,
        ):
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_count_result = MagicMock()
            mock_count_result.scalar_one.return_value = 0
            mock_session.execute = AsyncMock(return_value=mock_count_result)
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health/detailed")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "connected"
            assert data["recent_failed_jobs"] == 0

    def test_detailed_health_db_error(self, client):
        with patch("pic.api.health.engine") as mock_engine:
            # Both engine.connect and async_session will fail, caught by try/except
            mock_engine.connect.side_effect = Exception("connection refused")

            response = client.get("/health/detailed")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
