"""StorageBackend protocol and shared utilities."""

from typing import Any, Protocol, runtime_checkable

from pic.core.constants import S3_PREFIX_INBOX, S3_PREFIX_PROCESSED, S3_PREFIX_REJECTED, S3_PREFIX_THUMBNAILS

_ALLOWED_PREFIXES = (S3_PREFIX_INBOX, S3_PREFIX_PROCESSED, S3_PREFIX_REJECTED, S3_PREFIX_THUMBNAILS)


def validate_storage_key(key: str) -> None:
    """Validate that a storage key uses expected prefixes and has no path traversal."""
    if ".." in key:
        raise ValueError(f"Storage key contains path traversal: {key}")
    if not key.startswith(_ALLOWED_PREFIXES):
        raise ValueError(f"Storage key has unexpected prefix: {key}")


@runtime_checkable
class StorageBackend(Protocol):
    """Unified interface for all storage backends."""

    def upload(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None: ...
    def download(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def move(self, source_key: str, dest_key: str) -> None: ...
    def list_objects(self, prefix: str) -> list[str]: ...
    def get_url(self, key: str, expires_in: int = 900) -> str: ...
    def exists(self, key: str) -> bool: ...
