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
