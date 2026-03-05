"""Unit tests for S3StorageBackend."""

from unittest.mock import MagicMock, patch

import pytest

from pic.services.storage.base import StorageBackend


@pytest.fixture
def mock_boto_client():
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"image-data"))}
    client.list_objects_v2.return_value = {
        "Contents": [{"Key": "images/a.jpg"}, {"Key": "images/b.jpg"}],
        "IsTruncated": False,
    }
    client.generate_presigned_url.return_value = "https://s3.example.com/signed"
    client.head_object.return_value = {}
    return client


@pytest.fixture
def s3_backend(mock_boto_client):
    with patch("pic.services.storage.s3.boto3.client", return_value=mock_boto_client):
        from pic.services.storage.s3 import S3StorageBackend

        return S3StorageBackend(
            bucket="test-bucket",
            endpoint_url="https://s3.example.com",
            access_key_id="test-key",
            secret_access_key="test-secret",
        )


@pytest.mark.unit
class TestS3StorageBackend:
    def test_conforms_to_protocol(self, s3_backend):
        assert isinstance(s3_backend, StorageBackend)

    def test_upload(self, s3_backend, mock_boto_client):
        s3_backend.upload("images/test.jpg", b"data", "image/jpeg")
        mock_boto_client.put_object.assert_called_once_with(
            Bucket="test-bucket", Key="images/test.jpg", Body=b"data", ContentType="image/jpeg"
        )

    def test_download(self, s3_backend, mock_boto_client):
        result = s3_backend.download("images/test.jpg")
        assert result == b"image-data"
        mock_boto_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="images/test.jpg")

    def test_delete(self, s3_backend, mock_boto_client):
        s3_backend.delete("images/test.jpg")
        mock_boto_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="images/test.jpg")

    def test_move(self, s3_backend, mock_boto_client):
        s3_backend.move("images/test.jpg", "processed/test.jpg")
        mock_boto_client.copy_object.assert_called_once()
        mock_boto_client.delete_object.assert_called_once()

    def test_list_objects(self, s3_backend, mock_boto_client):
        keys = s3_backend.list_objects("images/")
        assert keys == ["images/a.jpg", "images/b.jpg"]

    def test_get_url(self, s3_backend, mock_boto_client):
        url = s3_backend.get_url("images/test.jpg", expires_in=300)
        assert url == "https://s3.example.com/signed"
        mock_boto_client.generate_presigned_url.assert_called_once()

    def test_exists_true(self, s3_backend, mock_boto_client):
        assert s3_backend.exists("images/test.jpg") is True

    def test_exists_false(self, s3_backend, mock_boto_client):
        from botocore.exceptions import ClientError

        mock_boto_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        assert s3_backend.exists("images/missing.jpg") is False
