"""Unit tests for web UI pages (DB-facing helpers are patched)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from pic.config import settings
from pic.services.browse import ClusterCard, GroupRow, Page, Thumb
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


def _thumb(i: str = "img-1") -> Thumb:
    return Thumb(
        id=i, filename=f"{i}.jpg", thumb_url=f"/files/thumbnails/{i}.jpg", full_url=f"/files/processed/{i}.jpg"
    )


@pytest.mark.unit
class TestClustersPage:
    def test_empty_state_points_to_runs(self, ui_client):
        with (
            patch("pic.ui.routes.browse.list_clusters", new_callable=AsyncMock, return_value=Page([], 0, 0, 24)),
            patch("pic.ui.routes.browse.unclustered_card", new_callable=AsyncMock, return_value=None),
        ):
            response = ui_client.get("/ui")
        assert response.status_code == 200
        assert "No clusters yet" in response.text
        assert 'href="/ui/jobs"' in response.text

    def test_renders_cards_and_load_more(self, ui_client):
        card = ClusterCard(ref="3", title="mugs", total_images=9, group_count=2, thumbnails=[_thumb()])
        with (
            patch("pic.ui.routes.browse.list_clusters", new_callable=AsyncMock, return_value=Page([card], 30, 0, 24)),
            patch("pic.ui.routes.browse.unclustered_card", new_callable=AsyncMock) as unclustered,
        ):
            response = ui_client.get("/ui")
        assert 'href="/ui/clusters/3"' in response.text
        assert "9 images · 2 groups" in response.text
        assert 'hx-get="/ui?offset=24"' in response.text
        unclustered.assert_not_awaited()  # only shown after the last page

    def test_htmx_next_page_returns_fragment_with_unclustered_last(self, ui_client):
        card = ClusterCard(ref="3", title="mugs", total_images=9, group_count=2, thumbnails=[])
        extra = ClusterCard(ref="unclustered", title="Unclustered", total_images=4, group_count=4, thumbnails=[])
        with (
            patch("pic.ui.routes.browse.list_clusters", new_callable=AsyncMock, return_value=Page([card], 25, 24, 24)),
            patch("pic.ui.routes.browse.unclustered_card", new_callable=AsyncMock, return_value=extra),
        ):
            response = ui_client.get("/ui?offset=24", headers=HX)
        assert "<html" not in response.text
        assert 'href="/ui/clusters/unclustered"' in response.text


@pytest.mark.unit
class TestClusterDetailPage:
    def test_unknown_cluster_is_404(self, ui_client):
        with patch("pic.ui.routes.browse.get_cluster_title", new_callable=AsyncMock, return_value=None):
            response = ui_client.get("/ui/clusters/999")
        assert response.status_code == 404

    def test_renders_groups_with_more_count_and_product_badge(self, ui_client):
        row = GroupRow(id=5, member_count=20, product_id=8, images=[_thumb()])
        with (
            patch("pic.ui.routes.browse.get_cluster_title", new_callable=AsyncMock, return_value="mugs"),
            patch("pic.ui.routes.browse.list_groups", new_callable=AsyncMock, return_value=Page([row], 1, 0, 20)),
        ):
            response = ui_client.get("/ui/clusters/3")
        assert response.status_code == 200
        assert "Group 5 · 20 images" in response.text
        assert "+19 more" in response.text
        assert "✓ product" in response.text
        assert 'src="/files/thumbnails/img-1.jpg"' in response.text
