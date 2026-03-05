"""Local filesystem storage backend for development."""

import logging
import shutil
from pathlib import Path

from pic.services.storage.base import validate_storage_key

logger = logging.getLogger(__name__)


class LocalStorageBackend:
    """StorageBackend implementation using local filesystem."""

    def __init__(self, root_path: Path, base_url: str) -> None:
        self._root = Path(root_path)
        self._base_url = base_url.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not str(path).startswith(str(self._root.resolve())):
            raise ValueError(f"Path escapes root directory: {key}")
        return path

    def upload(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info("Wrote %d bytes to %s", len(data), path)

    def download(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()
            logger.info("Deleted %s", path)

    def move(self, source_key: str, dest_key: str) -> None:
        validate_storage_key(source_key)
        validate_storage_key(dest_key)
        src = self._resolve(source_key)
        dst = self._resolve(dest_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        logger.info("Moved %s -> %s", source_key, dest_key)

    def list_objects(self, prefix: str) -> list[str]:
        prefix_path = self._resolve(prefix)
        if not prefix_path.exists():
            return []
        keys: list[str] = []
        for path in prefix_path.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(self._root)).replace("\\", "/")
                keys.append(rel)
        keys.sort()
        logger.info("Listed %d files under %s", len(keys), prefix)
        return keys

    def get_url(self, key: str, expires_in: int = 900) -> str:
        return f"{self._base_url}/{key}"

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()
