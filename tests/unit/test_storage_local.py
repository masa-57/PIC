"""Unit tests for LocalStorageBackend."""

import pytest

from pic.services.storage.base import StorageBackend


@pytest.fixture
def local_backend(tmp_path):
    from pic.services.storage.local import LocalStorageBackend

    return LocalStorageBackend(
        root_path=tmp_path,
        base_url="http://localhost:8000/files",
    )


@pytest.mark.unit
class TestLocalStorageBackend:
    def test_conforms_to_protocol(self, local_backend):
        assert isinstance(local_backend, StorageBackend)

    def test_upload_and_download(self, local_backend):
        local_backend.upload("images/test.jpg", b"image-data", "image/jpeg")
        result = local_backend.download("images/test.jpg")
        assert result == b"image-data"

    def test_delete(self, local_backend):
        local_backend.upload("images/test.jpg", b"data")
        local_backend.delete("images/test.jpg")
        assert not local_backend.exists("images/test.jpg")

    def test_move(self, local_backend):
        local_backend.upload("images/test.jpg", b"data")
        local_backend.move("images/test.jpg", "processed/test.jpg")
        assert not local_backend.exists("images/test.jpg")
        assert local_backend.exists("processed/test.jpg")
        assert local_backend.download("processed/test.jpg") == b"data"

    def test_list_objects(self, local_backend):
        local_backend.upload("images/a.jpg", b"a")
        local_backend.upload("images/b.jpg", b"b")
        local_backend.upload("processed/c.jpg", b"c")
        keys = local_backend.list_objects("images/")
        assert sorted(keys) == ["images/a.jpg", "images/b.jpg"]

    def test_get_url(self, local_backend):
        url = local_backend.get_url("processed/photo.jpg", expires_in=300)
        assert url == "http://localhost:8000/files/processed/photo.jpg"

    def test_exists_true(self, local_backend):
        local_backend.upload("images/test.jpg", b"data")
        assert local_backend.exists("images/test.jpg") is True

    def test_exists_false(self, local_backend):
        assert local_backend.exists("images/nope.jpg") is False

    def test_download_missing_raises(self, local_backend):
        with pytest.raises(FileNotFoundError):
            local_backend.download("images/nope.jpg")

    def test_rejects_path_traversal(self, local_backend):
        with pytest.raises(ValueError, match="path traversal"):
            local_backend.move("images/../etc/passwd", "processed/hacked")
