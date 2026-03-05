"""Storage backend abstraction layer."""

import functools

from pic.config import settings
from pic.services.storage.base import StorageBackend, validate_storage_key

__all__ = ["StorageBackend", "get_storage_backend", "validate_storage_key"]


def _create_storage_backend() -> StorageBackend:
    """Create a storage backend instance based on settings."""
    match settings.storage_backend:
        case "s3":
            from pic.services.storage.s3 import S3StorageBackend

            return S3StorageBackend(
                bucket=settings.s3_bucket,
                endpoint_url=settings.s3_endpoint_url,
                access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key,
            )
        case "gcs":
            from pic.services.storage.gcs import GCSStorageBackend

            return GCSStorageBackend(
                bucket_name=settings.gcs_bucket,
                project_id=settings.gcs_project_id,
                credentials_json=settings.gcs_credentials_json,
            )
        case "local":
            from pic.services.storage.local import LocalStorageBackend

            return LocalStorageBackend(
                root_path=settings.local_storage_path,
                base_url=settings.local_storage_base_url,
            )
        case _:
            raise ValueError(f"Unknown storage backend: {settings.storage_backend}")


@functools.lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    """Get or create the singleton storage backend."""
    return _create_storage_backend()
