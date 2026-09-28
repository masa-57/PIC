"""Unit tests for the web UI cookie session."""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from pic.config import settings
from pic.ui import auth


def _request(cookie: str | None = None, htmx: bool = False, path: str = "/ui/clusters/3") -> MagicMock:
    request = MagicMock()
    request.cookies = {auth.SESSION_COOKIE: cookie} if cookie else {}
    request.headers = {"HX-Request": "true"} if htmx else {}
    request.url.path = path
    return request


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")
    monkeypatch.setattr(settings, "auth_disabled", False)


@pytest.mark.unit
class TestSessionToken:
    def test_token_is_hmac_of_key_and_never_the_key(self):
        token = auth.session_token("secret-key")
        assert token != "secret-key"
        assert len(token) == 64
        assert auth.session_token("other") != token

    def test_valid_session_requires_current_key(self, auth_enabled, monkeypatch):
        cookie = auth.session_token("secret-key")
        assert auth.is_valid_session(cookie) is True
        monkeypatch.setattr(settings, "api_key", "rotated")
        assert auth.is_valid_session(cookie) is False
        assert auth.is_valid_session(None) is False


@pytest.mark.unit
class TestSafeNext:
    @pytest.mark.parametrize(
        "target", ["//evil.example", "https://evil.example", "/\\evil.example", "evil", "", None, "/api/v1/images"]
    )
    def test_rejects_off_site_or_non_ui_targets(self, target):
        assert auth.safe_next(target) == "/ui"

    def test_keeps_ui_paths(self):
        assert auth.safe_next("/ui/clusters/3?offset=20") == "/ui/clusters/3?offset=20"


@pytest.mark.unit
class TestRequireUiSession:
    def test_allows_when_auth_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "")
        monkeypatch.setattr(settings, "auth_disabled", True)
        asyncio.run(auth.require_ui_session(_request()))

    def test_misconfigured_returns_503(self, monkeypatch):
        monkeypatch.setattr(settings, "api_key", "")
        monkeypatch.setattr(settings, "auth_disabled", False)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth.require_ui_session(_request()))
        assert exc.value.status_code == 503

    def test_valid_cookie_passes(self, auth_enabled):
        asyncio.run(auth.require_ui_session(_request(cookie=auth.session_token("secret-key"))))

    def test_missing_or_wrong_cookie_requires_login(self, auth_enabled):
        for cookie in (None, "forged"):
            with pytest.raises(auth.LoginRequiredError) as exc:
                asyncio.run(auth.require_ui_session(_request(cookie=cookie)))
            assert exc.value.next_path == "/ui/clusters/3"


@pytest.mark.unit
class TestLoginRequiredHandler:
    def test_browser_request_redirects_to_login(self):
        response = asyncio.run(auth.login_required_handler(_request(), auth.LoginRequiredError("/ui/clusters/3")))
        assert response.status_code == 303
        assert response.headers["location"] == "/ui/login?next=/ui/clusters/3"

    def test_htmx_request_gets_hx_redirect(self):
        response = asyncio.run(auth.login_required_handler(_request(htmx=True), auth.LoginRequiredError("/ui")))
        assert response.status_code == 401
        assert response.headers["HX-Redirect"] == "/ui/login"


@pytest.mark.unit
class TestRequireHtmx:
    def test_rejects_plain_post(self):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(auth.require_htmx(_request()))
        assert exc.value.status_code == 400

    def test_accepts_htmx_post(self):
        asyncio.run(auth.require_htmx(_request(htmx=True)))
