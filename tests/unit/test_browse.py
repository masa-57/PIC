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
