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


@pytest.mark.unit
def test_protected_page_redirects_to_login(auth_client):
    response = auth_client.get("/ui/jobs", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/login?next=/ui/jobs"


def _job(status="completed", error=None, result=None):
    from datetime import datetime

    from pic.models.db import Job, JobStatus, JobType

    return Job(
        id="job-1",
        type=JobType.PIPELINE,
        status=JobStatus(status),
        progress=1.0 if status == "completed" else 0.3,
        error=error,
        result=result,
        created_at=datetime(2026, 9, 28, 12, 0),
        completed_at=None,
    )


@pytest.mark.unit
class TestRunsPage:
    def test_polls_only_while_a_job_is_active(self, ui_client):
        with (
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[_job("running")]),
            patch("pic.ui.routes.browse.typical_durations", new_callable=AsyncMock, return_value={}),
        ):
            active = ui_client.get("/ui/jobs")
        with patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[_job("completed")]):
            idle = ui_client.get("/ui/jobs")
        assert 'hx-trigger="every 3s"' in active.text
        assert 'hx-trigger="every 3s"' not in idle.text

    def test_shows_error_and_result_summary(self, ui_client):
        job = _job("failed", error="3 of 3 images failed to ingest; see worker logs", result='{"ingest_errors": 3}')
        with patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[job]):
            response = ui_client.get("/ui/jobs/table", headers=HX)
        assert "3 of 3 images failed to ingest" in response.text
        assert "ingest_errors 3" in response.text

    def test_run_requires_htmx_header(self, ui_client):
        assert ui_client.post("/ui/jobs/run/pipeline").status_code == 400

    def test_run_refuses_while_clustering_job_active(self, ui_client):
        with (
            patch("pic.ui.routes.browse.has_active_clustering_job", new_callable=AsyncMock, return_value=True),
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
            patch("pic.ui.routes.create_and_dispatch_job", new_callable=AsyncMock) as dispatch,
        ):
            response = ui_client.post("/ui/jobs/run/pipeline", headers=HX)
        assert response.status_code == 409
        assert "already running" in response.text
        dispatch.assert_not_awaited()

    def test_run_starts_job(self, ui_client):
        from pic.models.db import JobType

        with (
            patch("pic.ui.routes.browse.has_active_clustering_job", new_callable=AsyncMock, return_value=False),
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
            patch("pic.ui.routes.create_and_dispatch_job", new_callable=AsyncMock) as dispatch,
        ):
            response = ui_client.post("/ui/jobs/run/cluster", headers=HX)
        assert response.status_code == 200
        assert dispatch.await_args.args[1] == JobType.CLUSTER_FULL
        assert "Started" in response.text

    def test_queue_full_is_shown(self, ui_client):
        from fastapi import HTTPException

        with (
            patch("pic.ui.routes.browse.has_active_clustering_job", new_callable=AsyncMock, return_value=False),
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
            patch(
                "pic.ui.routes.create_and_dispatch_job",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=429, detail="Job queue is full"),
            ),
        ):
            response = ui_client.post("/ui/jobs/run/pipeline", headers=HX)
        assert response.status_code == 429
        assert "Job queue is full" in response.text

    def test_url_ingest_rejects_private_targets(self, ui_client):
        with patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]):
            response = ui_client.post("/ui/jobs/url-ingest", data={"urls": "http://127.0.0.1/a.jpg"}, headers=HX)
        assert response.status_code == 400

    def test_url_ingest_dispatches_with_auto_pipeline(self, ui_client):
        with (
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
            patch("pic.ui.routes.create_and_dispatch_job", new_callable=AsyncMock) as dispatch,
        ):
            response = ui_client.post(
                "/ui/jobs/url-ingest",
                data={"urls": "https://example.com/a.jpg\n\nhttps://example.com/b.jpg"},
                headers=HX,
            )
        assert response.status_code == 200
        params = dispatch.await_args.args[2]
        assert params == {"urls": ["https://example.com/a.jpg", "https://example.com/b.jpg"], "auto_pipeline": True}


@pytest.mark.unit
class TestUiErrorHandling:
    def test_htmx_framework_errors_do_not_swap(self, ui_client):
        # A failed poll must not replace #jobs with JSON (that would break the Runs page).
        from fastapi import HTTPException

        with patch(
            "pic.ui.routes.browse.recent_jobs",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=503, detail="Database unavailable"),
        ):
            response = ui_client.get("/ui/jobs/table", headers=HX)
        assert response.status_code == 503
        assert response.headers["HX-Reswap"] == "none"

    def test_htmx_validation_error_does_not_swap(self, ui_client):
        response = ui_client.get("/ui?offset=-1", headers=HX)
        assert response.status_code == 422
        assert response.headers["HX-Reswap"] == "none"

    def test_ui_rendered_errors_still_swap(self, ui_client):
        with (
            patch("pic.ui.routes.browse.has_active_clustering_job", new_callable=AsyncMock, return_value=True),
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
        ):
            response = ui_client.post("/ui/jobs/run/pipeline", headers=HX)
        assert response.status_code == 409
        assert "HX-Reswap" not in response.headers

    def test_api_errors_are_unchanged(self, ui_client):
        response = ui_client.get("/api/v1/no-such-route", headers=HX)
        assert response.status_code == 404
        assert "HX-Reswap" not in response.headers


@pytest.mark.unit
class TestUiImageCsp:
    def test_http_s3_endpoint_is_allowed_for_images(self, ui_client, monkeypatch):
        # Self-hosted MinIO often runs on plain http; presigned thumbnails must not be blocked.
        monkeypatch.setattr(settings, "storage_backend", "s3")
        monkeypatch.setattr(settings, "s3_endpoint_url", "http://nas.lan:9000/")
        csp = ui_client.get("/ui/login", follow_redirects=False).headers["content-security-policy"]
        assert "img-src 'self' https: data: http://nas.lan:9000;" in csp

    def test_local_backend_keeps_default_img_src(self, ui_client, monkeypatch):
        monkeypatch.setattr(settings, "storage_backend", "local")
        csp = ui_client.get("/ui/login", follow_redirects=False).headers["content-security-policy"]
        assert csp == "default-src 'self'; img-src 'self' https: data:; frame-ancestors 'none'"


@pytest.mark.unit
class TestAddImagesPanel:
    def test_shows_storage_and_source_tabs(self, ui_client, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(settings, "storage_backend", "local")
        monkeypatch.setattr(settings, "local_storage_path", Path("/data"))
        monkeypatch.setattr(settings, "gdrive_folder_id", "")
        with patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]):
            response = ui_client.get("/ui/jobs")
        text = response.text
        assert "Storage: <strong>Local filesystem</strong>" in text
        assert "/data/images/" in text
        for label in ("Local folder", "Already in storage", "Google Drive", "URLs"):
            assert label in text
        assert "PIC_GDRIVE_FOLDER_ID" in text  # not configured: tab explains what to set
        assert 'hx-post="/ui/jobs/run/gdrive"' not in text

    def test_gdrive_tab_has_sync_button_when_configured(self, ui_client, monkeypatch):
        monkeypatch.setattr(settings, "gdrive_folder_id", "folder-123")
        monkeypatch.setattr(settings, "gdrive_service_account_json", "{}")
        with patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]):
            response = ui_client.get("/ui/jobs")
        assert 'hx-post="/ui/jobs/run/gdrive"' in response.text
        assert "folder-123" in response.text

    def test_gdrive_sync_not_configured_is_rejected(self, ui_client, monkeypatch):
        monkeypatch.setattr(settings, "gdrive_folder_id", "")
        with (
            patch("pic.ui.routes.browse.has_active_clustering_job", new_callable=AsyncMock, return_value=False),
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
            patch("pic.ui.routes.create_and_dispatch_job", new_callable=AsyncMock) as dispatch,
        ):
            response = ui_client.post("/ui/jobs/run/gdrive", headers=HX)
        assert response.status_code == 400
        assert "Google Drive sync is not configured" in response.text
        dispatch.assert_not_awaited()

    def test_gdrive_sync_dispatches_job(self, ui_client, monkeypatch):
        from pic.models.db import JobType

        monkeypatch.setattr(settings, "gdrive_folder_id", "folder-123")
        monkeypatch.setattr(settings, "gdrive_service_account_json", "{}")
        with (
            patch("pic.ui.routes.browse.has_active_clustering_job", new_callable=AsyncMock, return_value=False),
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]),
            patch("pic.ui.routes.create_and_dispatch_job", new_callable=AsyncMock) as dispatch,
        ):
            response = ui_client.post("/ui/jobs/run/gdrive", headers=HX)
        assert response.status_code == 200
        assert dispatch.await_args.args[1] == JobType.GDRIVE_SYNC


@pytest.mark.unit
class TestRunProgress:
    def test_running_job_shows_bar_step_and_estimate(self, ui_client):
        from datetime import UTC, datetime, timedelta

        from pic.models.db import Job, JobStatus, JobType

        job = Job(
            id="job-9",
            type=JobType.PIPELINE,
            status=JobStatus.RUNNING,
            progress=0.3,
            created_at=datetime.now(UTC) - timedelta(seconds=60),
            completed_at=None,
        )
        with (
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[job]),
            patch("pic.ui.routes.browse.typical_durations", new_callable=AsyncMock, return_value={}),
        ):
            response = ui_client.get("/ui/jobs/table", headers=HX)
        assert '<progress max="100" value="30">' in response.text
        assert "Ingesting images" in response.text
        assert "left" in response.text

    def test_finished_job_shows_duration(self, ui_client):
        from datetime import UTC, datetime, timedelta

        from pic.models.db import Job, JobStatus, JobType

        created = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
        job = Job(
            id="job-8",
            type=JobType.CLUSTER_FULL,
            status=JobStatus.COMPLETED,
            progress=1.0,
            created_at=created,
            completed_at=created + timedelta(seconds=26),
        )
        with (
            patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[job]),
            patch("pic.ui.routes.browse.typical_durations", new_callable=AsyncMock, return_value={}),
        ):
            response = ui_client.get("/ui/jobs/table", headers=HX)
        assert "Took 26s" in response.text


@pytest.mark.unit
class TestStaticCacheBusting:
    def test_static_urls_carry_a_content_version(self, auth_client):
        # Static files are cached for a day; a changed file must get a new URL.
        import re

        from pic.ui.templating import static_version

        html = auth_client.get("/ui/login").text
        assert re.search(r'/ui/static/pic\.css\?v=[0-9a-f]{12}"', html)
        assert re.search(r'/ui/static/htmx\.min\.js\?v=[0-9a-f]{12}"', html)
        assert f"?v={static_version}" in html


@pytest.mark.unit
def test_pending_job_row_says_usual_duration(ui_client):
    from datetime import UTC, datetime

    from pic.models.db import Job, JobStatus, JobType

    job = Job(
        id="job-7", type=JobType.CLUSTER_FULL, status=JobStatus.PENDING, progress=0.0, created_at=datetime.now(UTC)
    )
    with (
        patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[job]),
        patch(
            "pic.ui.routes.browse.typical_durations", new_callable=AsyncMock, return_value={JobType.CLUSTER_FULL: 7.0}
        ),
    ):
        response = ui_client.get("/ui/jobs/table", headers=HX)
    assert "usually takes ~7s" in response.text


@pytest.mark.unit
class TestFolderUpload:
    def test_runs_page_has_folder_picker_and_script(self, ui_client):
        with patch("pic.ui.routes.browse.recent_jobs", new_callable=AsyncMock, return_value=[]):
            text = ui_client.get("/ui/jobs").text
        assert "Local folder" in text
        assert "webkitdirectory" in text
        assert "/ui/static/upload.js?v=" in text

    def test_upload_requires_htmx_header(self, ui_client):
        response = ui_client.post("/ui/upload", files=[("files", ("a.jpg", b"x", "image/jpeg"))])
        assert response.status_code == 400

    def test_upload_returns_counts(self, ui_client):
        from pic.services.uploads import UploadResult

        with patch(
            "pic.ui.routes.store_uploads",
            new_callable=AsyncMock,
            return_value=UploadResult(stored=["images/k_a.jpg"]),
        ):
            response = ui_client.post("/ui/upload", files=[("files", ("sub/a.jpg", b"x", "image/jpeg"))], headers=HX)
        assert response.status_code == 200
        assert response.json()["stored"] == 1
