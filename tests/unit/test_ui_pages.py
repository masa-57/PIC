"""Unit tests for web UI pages (DB-facing helpers are patched)."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from pic.config import settings
from pic.ui import auth

HX = {"HX-Request": "true"}


@pytest.fixture
def ui_client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "auth_disabled", True)
    from pic.api.deps import get_db
    from pic.main import app

    async def _db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(monkeypatch, ui_client):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(settings, "auth_disabled", False)
    return ui_client


@pytest.mark.unit
class TestShell:
    def test_static_htmx_is_served_and_cacheable(self, ui_client):
        response = ui_client.get("/ui/static/htmx.min.js")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=86400"

    def test_login_redirects_home_when_auth_disabled(self, ui_client):
        response = ui_client.get("/ui/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/ui"

    def test_login_with_wrong_key_shows_error(self, auth_client):
        response = auth_client.post("/ui/login", data={"api_key": "nope", "next": "/ui"})
        assert response.status_code == 401
        assert "Wrong API key" in response.text

    def test_login_sets_hardened_cookie_and_redirects_to_safe_next(self, auth_client):
        response = auth_client.post(
            "/ui/login", data={"api_key": "secret-key", "next": "//evil.example"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/ui"
        cookie = response.headers["set-cookie"]
        assert f"{auth.SESSION_COOKIE}={auth.session_token('secret-key')}" in cookie
        for attribute in ("HttpOnly", "SameSite=strict", "Path=/ui", "Max-Age=2592000"):
            assert attribute.lower() in cookie.lower()

    def test_logout_clears_cookie(self, auth_client):
        response = auth_client.post("/ui/logout", follow_redirects=False)
        assert response.status_code == 303
        assert f'{auth.SESSION_COOKIE}=""' in response.headers["set-cookie"]

    def test_ui_csp_and_no_store(self, auth_client):
        response = auth_client.get("/ui/login")
        assert response.headers["content-security-policy"] == (
            "default-src 'self'; img-src 'self' https: data:; frame-ancestors 'none'"
        )
        assert response.headers["cache-control"] == "no-store"
        assert 'name="htmx-config"' in response.text

    def test_legacy_view_redirects_to_ui(self, ui_client):
        response = ui_client.get("/api/v1/clusters/view", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/ui"
