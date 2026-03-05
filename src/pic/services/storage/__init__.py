"""Storage backend abstraction layer."""

from pic.services.storage.base import StorageBackend, validate_storage_key

__all__ = ["StorageBackend", "validate_storage_key"]
