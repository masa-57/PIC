"""Unit tests for storing uploaded images in the storage inbox."""

from unittest.mock import patch

import pytest

from pic.services import uploads
from pic.services.uploads import UploadedFile


@pytest.mark.unit
class TestInboxKey:
    def test_keeps_basename_under_inbox_with_unique_prefix(self):
        key = uploads.inbox_key("holiday/mugs/front.JPG")
        assert key.startswith("images/")
        assert key.endswith("_front.JPG")
        assert uploads.inbox_key("front.JPG") != uploads.inbox_key("front.JPG")

    @pytest.mark.parametrize("name", ["../../etc/passwd.jpg", "..\\..\\evil.jpg", "/abs/path/x.jpg"])
    def test_strips_directories_and_traversal(self, name):
        key = uploads.inbox_key(name)
        assert key.count("/") == 1
        assert ".." not in key
        assert "\\" not in key


@pytest.mark.unit
class TestStoreUploads:
    async def test_stores_images_and_skips_others(self):
        files = [
            UploadedFile(name="a/one.jpg", data=b"jpeg-bytes"),
            UploadedFile(name="a/notes.txt", data=b"text"),
            UploadedFile(name="a/empty.png", data=b""),
        ]
        with patch("pic.services.uploads.upload_to_s3") as upload:
            result = await uploads.store_uploads(files)

        assert len(result.stored) == 1
        assert result.stored[0].endswith("_one.jpg")
        upload.assert_called_once()
        data, key = upload.call_args.args[:2]
        assert (data, key) == (b"jpeg-bytes", result.stored[0])
        assert upload.call_args.kwargs["content_type"] == "image/jpeg"
        assert {s["name"]: s["reason"] for s in result.skipped} == {
            "a/notes.txt": "not a supported image type",
            "a/empty.png": "empty file",
        }

    async def test_skips_files_over_the_size_limit(self, monkeypatch):
        monkeypatch.setattr(uploads.settings, "max_upload_size_mb", 1)
        big = UploadedFile(name="big.jpg", data=b"x" * (1024 * 1024 + 1))
        with patch("pic.services.uploads.upload_to_s3") as upload:
            result = await uploads.store_uploads([big])
        assert result.stored == []
        assert result.skipped == [{"name": "big.jpg", "reason": "larger than 1 MB"}]
        upload.assert_not_called()

    async def test_storage_failure_is_reported_per_file(self):
        with patch("pic.services.uploads.upload_to_s3", side_effect=OSError("disk full")):
            result = await uploads.store_uploads([UploadedFile(name="a.jpg", data=b"x")])
        assert result.stored == []
        assert result.skipped == [{"name": "a.jpg", "reason": "could not be stored"}]
