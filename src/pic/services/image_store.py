import functools
import io
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ConnectionError as BotoConnectionError
from botocore.exceptions import EndpointConnectionError
from PIL import Image as PILImage
from PIL import UnidentifiedImageError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pic.config import settings
from pic.core.constants import S3_PREFIX_INBOX, S3_PREFIX_PROCESSED, S3_PREFIX_REJECTED, S3_PREFIX_THUMBNAILS
from pic.services.image_validation import validate_pixel_count

logger = logging.getLogger(__name__)


@runtime_checkable
class S3ClientProtocol(Protocol):
    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def copy_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...
    def generate_presigned_url(self, client_method: str, **kwargs: Any) -> str: ...


_s3_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(
        (BotoConnectionError, EndpointConnectionError, ConnectionError, TimeoutError, OSError)
    ),
    reraise=True,
)


@functools.lru_cache(maxsize=1)
def get_s3_client() -> S3ClientProtocol:
    client: S3ClientProtocol = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
        region_name="auto",
        config=BotoConfig(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 0},  # retries handled by tenacity
        ),
    )
    return client


@dataclass
class _PresignedUrlCacheEntry:
    url: str
    expires_at_monotonic: float


_PRESIGNED_URL_CACHE_MAXSIZE = 1024
_PRESIGNED_URL_CACHE_SAFETY_MARGIN_SECONDS = 60
_PRESIGNED_URL_CACHE: dict[tuple[str, int], _PresignedUrlCacheEntry] = {}
_PRESIGNED_URL_CACHE_LOCK = threading.Lock()


@_s3_retry
def upload_to_s3(file_bytes: bytes, s3_key: str, content_type: str = "image/jpeg") -> None:
    s3 = get_s3_client()
    s3.put_object(
        Bucket=settings.s3_bucket,
        Key=s3_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    logger.info("Uploaded %d bytes to %s", len(file_bytes), s3_key)


@_s3_retry
def download_from_s3(s3_key: str) -> bytes:
    s3 = get_s3_client()
    response = s3.get_object(Bucket=settings.s3_bucket, Key=s3_key)
    return bytes(response["Body"].read())


_ALLOWED_PREFIXES = (S3_PREFIX_INBOX, S3_PREFIX_PROCESSED, S3_PREFIX_REJECTED, S3_PREFIX_THUMBNAILS)


def _validate_s3_key(key: str) -> None:
    """Validate that an S3 key uses expected prefixes and has no path traversal."""
    if ".." in key:
        raise ValueError(f"S3 key contains path traversal: {key}")
    if not key.startswith(_ALLOWED_PREFIXES):
        raise ValueError(f"S3 key has unexpected prefix: {key}")


@_s3_retry
def move_s3_object(source_key: str, dest_key: str) -> None:
    """Move an S3 object by copying then deleting the original."""
    _validate_s3_key(source_key)
    _validate_s3_key(dest_key)
    s3 = get_s3_client()
    bucket = settings.s3_bucket
    s3.copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": source_key},
        Key=dest_key,
    )
    s3.delete_object(Bucket=bucket, Key=source_key)
    logger.info("Moved %s → %s", source_key, dest_key)


def generate_thumbnail(image_bytes_or_pil: bytes | PILImage.Image) -> bytes:
    """Generate a JPEG thumbnail from image bytes or PIL Image.

    Accepts either raw bytes or an already-opened PIL Image to avoid redundant opens.
    """
    if isinstance(image_bytes_or_pil, PILImage.Image):
        img = image_bytes_or_pil.copy()
    else:
        img = PILImage.open(io.BytesIO(image_bytes_or_pil))
    try:
        validate_pixel_count(img)
        img.thumbnail((settings.thumbnail_width, settings.thumbnail_height))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()
    finally:
        img.close()


def get_image_dimensions(image_bytes_or_pil: bytes | PILImage.Image) -> tuple[int, int]:
    """Return (width, height) of an image.

    Accepts either raw bytes or an already-opened PIL Image to avoid redundant opens.
    """
    if isinstance(image_bytes_or_pil, PILImage.Image):
        validate_pixel_count(image_bytes_or_pil)
        return image_bytes_or_pil.size
    try:
        with PILImage.open(io.BytesIO(image_bytes_or_pil)) as img:
            validate_pixel_count(img)
            return img.size
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Invalid or unsupported image bytes") from exc


@_s3_retry
def list_s3_objects(prefix: str) -> list[str]:
    """List all object keys under a prefix, handling pagination."""
    s3 = get_s3_client()
    keys: list[str] = []
    continuation_token = None

    while True:
        kwargs: dict[str, str] = {"Bucket": settings.s3_bucket, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            keys.append(obj["Key"])

        if not response.get("IsTruncated"):
            break
        continuation_token = response["NextContinuationToken"]

    logger.info("Listed %d objects under %s", len(keys), prefix)
    return keys


@_s3_retry
def delete_s3_object(s3_key: str) -> None:
    """Delete a single S3 object."""
    s3 = get_s3_client()
    s3.delete_object(Bucket=settings.s3_bucket, Key=s3_key)
    logger.info("Deleted %s", s3_key)


def _generate_presigned_url_cached(s3_key: str, bounded_expiry: int) -> str:
    """Internal cached presigned URL generator with TTL and bounded size."""
    cache_key = (s3_key, bounded_expiry)
    now = time.monotonic()

    with _PRESIGNED_URL_CACHE_LOCK:
        cached = _PRESIGNED_URL_CACHE.get(cache_key)
        if cached and cached.expires_at_monotonic > now:
            return cached.url
        _PRESIGNED_URL_CACHE.pop(cache_key, None)

    s3 = get_s3_client()
    presigned_url = str(
        s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": s3_key},
            ExpiresIn=bounded_expiry,
        )
    )
    ttl_seconds = max(1, bounded_expiry - _PRESIGNED_URL_CACHE_SAFETY_MARGIN_SECONDS)

    with _PRESIGNED_URL_CACHE_LOCK:
        now_after = time.monotonic()
        # Another thread may have populated the cache while we were generating the URL.
        cached_after = _PRESIGNED_URL_CACHE.get(cache_key)
        if cached_after and cached_after.expires_at_monotonic > now_after:
            return cached_after.url

        expired_keys = [k for k, v in _PRESIGNED_URL_CACHE.items() if v.expires_at_monotonic <= now_after]
        for key in expired_keys:
            _PRESIGNED_URL_CACHE.pop(key, None)
        while len(_PRESIGNED_URL_CACHE) >= _PRESIGNED_URL_CACHE_MAXSIZE:
            _PRESIGNED_URL_CACHE.pop(next(iter(_PRESIGNED_URL_CACHE)))
        _PRESIGNED_URL_CACHE[cache_key] = _PresignedUrlCacheEntry(
            url=presigned_url,
            expires_at_monotonic=now_after + ttl_seconds,
        )

    return presigned_url


def _clear_presigned_url_cache() -> None:
    """Testing helper to reset presigned URL cache state."""
    with _PRESIGNED_URL_CACHE_LOCK:
        _PRESIGNED_URL_CACHE.clear()


def generate_presigned_url(s3_key: str, expires_in: int | None = None) -> str:
    """Generate a presigned URL for an S3 object. Results are cached by (key, expiry)."""
    requested_expiry = settings.presigned_url_expiry if expires_in is None else expires_in
    bounded_expiry = max(1, min(requested_expiry, settings.presigned_url_max_expiry))
    return _generate_presigned_url_cached(s3_key, bounded_expiry)
