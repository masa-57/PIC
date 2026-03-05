"""Unit tests for storage backend factory."""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestGetStorageBackend:
    def test_returns_s3_by_default(self):
        with patch("pic.services.storage.settings") as mock_settings:
            mock_settings.storage_backend = "s3"
            mock_settings.s3_bucket = "test"
            mock_settings.s3_endpoint_url = "https://s3.example.com"
            mock_settings.s3_access_key_id = "key"
            mock_settings.s3_secret_access_key = "secret"

            from pic.services.storage import _create_storage_backend

            backend = _create_storage_backend()
            from pic.services.storage.s3 import S3StorageBackend

            assert isinstance(backend, S3StorageBackend)

    def test_returns_local_backend(self, tmp_path):
        with patch("pic.services.storage.settings") as mock_settings:
            mock_settings.storage_backend = "local"
            mock_settings.local_storage_path = tmp_path
            mock_settings.local_storage_base_url = "http://localhost:8000/files"

            from pic.services.storage import _create_storage_backend

            backend = _create_storage_backend()
            from pic.services.storage.local import LocalStorageBackend

            assert isinstance(backend, LocalStorageBackend)

    def test_raises_on_unknown_backend(self):
        with patch("pic.services.storage.settings") as mock_settings:
            mock_settings.storage_backend = "azure"

            from pic.services.storage import _create_storage_backend

            with pytest.raises(ValueError, match="Unknown storage backend"):
                _create_storage_backend()
