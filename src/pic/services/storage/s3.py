"""S3-compatible storage backend (AWS S3, Cloudflare R2, MinIO)."""

import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, ConnectionError as BotoConnectionError, EndpointConnectionError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pic.services.storage.base import StorageBackend, validate_storage_key

logger = logging.getLogger(__name__)

_s3_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(
        (BotoConnectionError, EndpointConnectionError, ConnectionError, TimeoutError, OSError)
    ),
    reraise=True,
)


class S3StorageBackend:
    """StorageBackend implementation for S3-compatible object stores."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            region_name="auto",
            config=BotoConfig(
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 0},
            ),
        )

    @_s3_retry
    def upload(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        logger.info("Uploaded %d bytes to %s", len(data), key)

    @_s3_retry
    def download(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return bytes(response["Body"].read())

    @_s3_retry
    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
        logger.info("Deleted %s", key)

    @_s3_retry
    def move(self, source_key: str, dest_key: str) -> None:
        validate_storage_key(source_key)
        validate_storage_key(dest_key)
        self._client.copy_object(
            Bucket=self._bucket,
            CopySource={"Bucket": self._bucket, "Key": source_key},
            Key=dest_key,
        )
        self._client.delete_object(Bucket=self._bucket, Key=source_key)
        logger.info("Moved %s -> %s", source_key, dest_key)

    @_s3_retry
    def list_objects(self, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token = None
        while True:
            kwargs: dict[str, str] = {"Bucket": self._bucket, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            for obj in response.get("Contents", []):
                keys.append(obj["Key"])
            if not response.get("IsTruncated"):
                break
            continuation_token = response["NextContinuationToken"]
        logger.info("Listed %d objects under %s", len(keys), prefix)
        return keys

    @_s3_retry
    def get_url(self, key: str, expires_in: int = 900) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise
