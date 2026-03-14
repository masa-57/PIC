import io
import logging
import threading
import time
from dataclasses import dataclass

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from pic.config import settings
from pic.services.image_validation import validate_pixel_count
from pic.services.storage import get_storage_backend

logger = logging.getLogger(__name__)


@dataclass
class _PresignedUrlCacheEntry:
    url: str
    expires_at_monotonic: float


_PRESIGNED_URL_CACHE_MAXSIZE = 1024
_PRESIGNED_URL_CACHE_SAFETY_MARGIN_SECONDS = 60
_PRESIGNED_URL_CACHE: dict[tuple[str, int], _PresignedUrlCacheEntry] = {}
_PRESIGNED_URL_CACHE_LOCK = threading.Lock()


def upload_to_s3(file_bytes: bytes, s3_key: str, content_type: str = "image/jpeg") -> None:
    backend = get_storage_backend()
    backend.upload(s3_key, file_bytes, content_type)


def download_from_s3(s3_key: str) -> bytes:
    backend = get_storage_backend()
    return backend.download(s3_key)


def move_s3_object(source_key: str, dest_key: str) -> None:
    """Move an object by copying then deleting the original."""
    backend = get_storage_backend()
    backend.move(source_key, dest_key)


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


def list_s3_objects(prefix: str) -> list[str]:
    """List all object keys under a prefix, handling pagination."""
    backend = get_storage_backend()
    return backend.list_objects(prefix)


def delete_s3_object(s3_key: str) -> None:
    """Delete a single object."""
    backend = get_storage_backend()
    backend.delete(s3_key)


def _generate_presigned_url_cached(s3_key: str, bounded_expiry: int) -> str:
    """Internal cached presigned URL generator with TTL and bounded size."""
    cache_key = (s3_key, bounded_expiry)
    now = time.monotonic()

    with _PRESIGNED_URL_CACHE_LOCK:
        cached = _PRESIGNED_URL_CACHE.get(cache_key)
        if cached and cached.expires_at_monotonic > now:
            return cached.url
        _PRESIGNED_URL_CACHE.pop(cache_key, None)

    backend = get_storage_backend()
    presigned_url = backend.get_url(s3_key, expires_in=bounded_expiry)
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
    """Generate a presigned URL for an object. Results are cached by (key, expiry)."""
    requested_expiry = settings.presigned_url_expiry if expires_in is None else expires_in
    bounded_expiry = max(1, min(requested_expiry, settings.presigned_url_max_expiry))
    return _generate_presigned_url_cached(s3_key, bounded_expiry)
