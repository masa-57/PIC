"""Unit tests for GCSStorageBackend."""

from unittest.mock import MagicMock, patch

import pytest

from pic.services.storage.base import StorageBackend


@pytest.fixture
def mock_gcs_client():
    client = MagicMock()
    bucket = MagicMock()
    client.bucket.return_value = bucket

    blob = MagicMock()
    blob.download_as_bytes.return_value = b"image-data"
    blob.exists.return_value = True
    blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"
    bucket.blob.return_value = blob
    bucket.list_blobs.return_value = [MagicMock(name="images/a.jpg"), MagicMock(name="images/b.jpg")]

    return client, bucket, blob


@pytest.fixture
def gcs_backend(mock_gcs_client):
    client, bucket, blob = mock_gcs_client
    mock_credentials = MagicMock()
    with (
        patch("pic.services.storage.gcs.storage.Client", return_value=client),
        patch(
            "pic.services.storage.gcs.service_account.Credentials.from_service_account_info",
            return_value=mock_credentials,
        ),
    ):
        from pic.services.storage.gcs import GCSStorageBackend

        return GCSStorageBackend(
            bucket_name="test-bucket",
            project_id="test-project",
            credentials_json='{"type": "service_account", "project_id": "test"}',
        )


@pytest.mark.unit
class TestGCSStorageBackend:
    def test_conforms_to_protocol(self, gcs_backend):
        assert isinstance(gcs_backend, StorageBackend)

    def test_upload(self, gcs_backend, mock_gcs_client):
        _, bucket, blob = mock_gcs_client
        gcs_backend.upload("images/test.jpg", b"data", "image/jpeg")
        blob.upload_from_string.assert_called_once_with(b"data", content_type="image/jpeg")

    def test_download(self, gcs_backend, mock_gcs_client):
        result = gcs_backend.download("images/test.jpg")
        assert result == b"image-data"

    def test_delete(self, gcs_backend, mock_gcs_client):
        _, _, blob = mock_gcs_client
        gcs_backend.delete("images/test.jpg")
        blob.delete.assert_called_once()

    def test_list_objects(self, gcs_backend, mock_gcs_client):
        keys = gcs_backend.list_objects("images/")
        assert len(keys) == 2

    def test_exists_true(self, gcs_backend):
        assert gcs_backend.exists("images/test.jpg") is True

    def test_exists_false(self, gcs_backend, mock_gcs_client):
        _, _, blob = mock_gcs_client
        blob.exists.return_value = False
        assert gcs_backend.exists("images/missing.jpg") is False
