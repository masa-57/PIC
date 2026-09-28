"""Unit tests for UI read-model helpers."""

from unittest.mock import patch

import pytest

from pic.services import browse


@pytest.mark.unit
class TestImageUrl:
    def test_local_backend_uses_relative_files_path(self, monkeypatch):
        # Compose sets an absolute localhost base URL; a relative path keeps
        # images working when the UI is opened as 127.0.0.1 (CSP 'self').
        monkeypatch.setattr(browse.settings, "storage_backend", "local")
        monkeypatch.setattr(browse.settings, "local_storage_base_url", "http://localhost:8000/files")
        assert browse.image_url("thumbnails/a.jpg") == "/files/thumbnails/a.jpg"

    def test_remote_backend_uses_presigned_url(self, monkeypatch):
        monkeypatch.setattr(browse.settings, "storage_backend", "s3")
        with patch("pic.services.browse.generate_presigned_url", return_value="https://s3/x?sig") as sign:
            assert browse.image_url("processed/a.jpg") == "https://s3/x?sig"
        sign.assert_called_once_with("processed/a.jpg")


@pytest.mark.unit
class TestThumbFor:
    def test_falls_back_to_full_image_without_thumbnail(self, monkeypatch):
        monkeypatch.setattr(browse.settings, "storage_backend", "local")
        thumb = browse.thumb_for("img-1", "a.jpg", "processed/a.jpg", None)
        assert thumb.thumb_url == thumb.full_url == "/files/processed/a.jpg"


@pytest.mark.unit
class TestPage:
    def test_has_more_and_next_offset(self):
        page = browse.Page(items=[1, 2], total=5, offset=2, limit=2)
        assert page.has_more is True
        assert page.next_offset == 4
        assert browse.Page(items=[5], total=5, offset=4, limit=2).has_more is False


@pytest.mark.unit
class TestGroupRow:
    def test_more_counts_hidden_images(self):
        row = browse.GroupRow(id=1, member_count=300, product_id=None, images=[])
        assert row.more == 300


@pytest.mark.unit
class TestSummarizeResult:
    def test_keeps_scalar_fields_and_skips_lists(self):
        result = '{"images_ingested": 39, "failed_image_ids": ["a"], "l1_groups": 19}'
        assert browse.summarize_result(result) == "images_ingested 39 · l1_groups 19"

    def test_handles_empty_and_invalid(self):
        assert browse.summarize_result(None) == ""
        assert browse.summarize_result("not json") == ""


@pytest.mark.unit
class TestStorageInfo:
    def test_local_backend_shows_inbox_folder(self, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(browse.settings, "storage_backend", "local")
        monkeypatch.setattr(browse.settings, "local_storage_path", Path("/data"))
        info = browse.storage_info()
        assert info.label == "Local filesystem"
        assert info.inbox == "/data/images/"
        assert "./data/images" in (info.hint or "")

    def test_s3_compatible_backend_shows_endpoint_host_not_credentials(self, monkeypatch):
        monkeypatch.setattr(browse.settings, "storage_backend", "s3")
        monkeypatch.setattr(browse.settings, "s3_bucket", "pic-images")
        monkeypatch.setattr(browse.settings, "s3_endpoint_url", "http://user:secret@nas.lan:9000")
        info = browse.storage_info()
        assert info.label == "S3-compatible at nas.lan:9000"
        assert info.inbox == "s3://pic-images/images/"
        assert "secret" not in info.label + info.inbox

    def test_aws_s3_without_endpoint(self, monkeypatch):
        monkeypatch.setattr(browse.settings, "storage_backend", "s3")
        monkeypatch.setattr(browse.settings, "s3_endpoint_url", "")
        assert browse.storage_info().label == "Amazon S3"

    def test_gcs_backend(self, monkeypatch):
        monkeypatch.setattr(browse.settings, "storage_backend", "gcs")
        monkeypatch.setattr(browse.settings, "gcs_bucket", "pics")
        info = browse.storage_info()
        assert (info.label, info.inbox) == ("Google Cloud Storage", "gs://pics/images/")


@pytest.mark.unit
class TestGdriveConfigured:
    def test_needs_both_settings(self, monkeypatch):
        monkeypatch.setattr(browse.settings, "gdrive_folder_id", "folder")
        monkeypatch.setattr(browse.settings, "gdrive_service_account_json", "")
        assert browse.gdrive_configured() is False
        monkeypatch.setattr(browse.settings, "gdrive_service_account_json", "{}")
        assert browse.gdrive_configured() is True


def _job(job_type, status, progress=0.0, age_s=60.0, took_s=None):
    from datetime import UTC, datetime, timedelta

    from pic.models.db import Job

    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    created = now - timedelta(seconds=age_s)
    completed = created + timedelta(seconds=took_s) if took_s is not None else None
    job = Job(id="j", type=job_type, status=status, progress=progress, created_at=created, completed_at=completed)
    return job, now


@pytest.mark.unit
class TestFormatDuration:
    @pytest.mark.parametrize(("seconds", "text"), [(0, "0s"), (12.4, "12s"), (72, "1m 12s"), (3900, "1h 5m")])
    def test_formats(self, seconds, text):
        assert browse.format_duration(seconds) == text


@pytest.mark.unit
class TestJobView:
    def test_pending_waits_for_worker(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.PIPELINE, JobStatus.PENDING)
        view = browse.job_view(job, now, {})
        assert (view.step, view.percent, view.active) == ("Waiting for worker", 0, True)

    def test_pipeline_ingest_estimates_from_progress_rate(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.PIPELINE, JobStatus.RUNNING, progress=0.3, age_s=60)
        view = browse.job_view(job, now, {})
        assert view.step == "Ingesting images"
        assert view.percent == 30
        assert view.elapsed == "1m 0s"
        assert view.remaining == "2m 20s"  # 60s * 0.7 / 0.3

    def test_other_jobs_estimate_from_typical_duration(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.CLUSTER_FULL, JobStatus.RUNNING, age_s=10)
        view = browse.job_view(job, now, {JobType.CLUSTER_FULL: 30.0})
        assert (view.step, view.remaining) == ("Clustering", "20s")

    def test_overdue_job_says_almost_done(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.CLUSTER_FULL, JobStatus.RUNNING, age_s=45)
        assert browse.job_view(job, now, {JobType.CLUSTER_FULL: 30.0}).remaining == "almost done"

    def test_no_history_has_no_estimate(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.URL_INGEST, JobStatus.RUNNING, age_s=5)
        assert browse.job_view(job, now, {}).remaining is None

    def test_finished_job_reports_duration(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.PIPELINE, JobStatus.COMPLETED, progress=1.0, age_s=100, took_s=26)
        view = browse.job_view(job, now, {})
        assert (view.active, view.took, view.percent) == (False, "26s", 100)


@pytest.mark.unit
class TestPendingExpectation:
    def test_pending_job_shows_typical_duration(self):
        from pic.models.db import JobStatus, JobType

        job, now = _job(JobType.CLUSTER_FULL, JobStatus.PENDING, age_s=2)
        view = browse.job_view(job, now, {JobType.CLUSTER_FULL: 7.0})
        assert view.typical == "7s"
        assert view.remaining is None
