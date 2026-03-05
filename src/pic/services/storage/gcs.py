"""Google Cloud Storage backend."""

import json
import logging
from datetime import timedelta

from google.cloud import storage
from google.oauth2 import service_account
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pic.services.storage.base import validate_storage_key

logger = logging.getLogger(__name__)

_gcs_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)


class GCSStorageBackend:
    """StorageBackend implementation for Google Cloud Storage."""

    def __init__(self, bucket_name: str, project_id: str, credentials_json: str) -> None:
        creds_data = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(creds_data)  # type: ignore[no-untyped-call]
        client = storage.Client(project=project_id, credentials=credentials)
        self._bucket = client.bucket(bucket_name)
        self._credentials = credentials

    @_gcs_retry
    def upload(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_string(data, content_type=content_type)
        logger.info("Uploaded %d bytes to gs://%s/%s", len(data), self._bucket.name, key)

    @_gcs_retry
    def download(self, key: str) -> bytes:
        blob = self._bucket.blob(key)
        return bytes(blob.download_as_bytes())

    @_gcs_retry
    def delete(self, key: str) -> None:
        blob = self._bucket.blob(key)
        blob.delete()
        logger.info("Deleted gs://%s/%s", self._bucket.name, key)

    def move(self, source_key: str, dest_key: str) -> None:
        validate_storage_key(source_key)
        validate_storage_key(dest_key)
        source_blob = self._bucket.blob(source_key)
        self._bucket.copy_blob(source_blob, self._bucket, dest_key)
        source_blob.delete()
        logger.info("Moved %s -> %s", source_key, dest_key)

    @_gcs_retry
    def list_objects(self, prefix: str) -> list[str]:
        blobs = self._bucket.list_blobs(prefix=prefix)
        keys = [blob.name for blob in blobs]
        logger.info("Listed %d objects under %s", len(keys), prefix)
        return keys

    def get_url(self, key: str, expires_in: int = 900) -> str:
        blob = self._bucket.blob(key)
        url: str = blob.generate_signed_url(
            expiration=timedelta(seconds=expires_in),
            credentials=self._credentials,
            version="v4",
        )
        return url

    def exists(self, key: str) -> bool:
        blob = self._bucket.blob(key)
        result: bool = blob.exists()
        return result
