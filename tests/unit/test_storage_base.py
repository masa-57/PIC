"""Unit tests for StorageBackend protocol."""

import pytest

from pic.services.storage.base import StorageBackend, validate_storage_key


@pytest.mark.unit
class TestValidateStorageKey:
    def test_valid_inbox_key(self):
        validate_storage_key("images/photo.jpg")

    def test_valid_processed_key(self):
        validate_storage_key("processed/photo.jpg")

    def test_valid_thumbnail_key(self):
        validate_storage_key("thumbnails/abc.jpg")

    def test_valid_rejected_key(self):
        validate_storage_key("rejected/dup.jpg")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_storage_key("images/../etc/passwd")

    def test_rejects_unknown_prefix(self):
        with pytest.raises(ValueError, match="unexpected prefix"):
            validate_storage_key("secret/data.bin")


@pytest.mark.unit
class TestStorageBackendProtocol:
    def test_protocol_is_runtime_checkable(self):
        assert isinstance(StorageBackend, type)

    def test_non_conforming_class_fails_check(self):
        class NotABackend:
            pass

        assert not isinstance(NotABackend(), StorageBackend)
