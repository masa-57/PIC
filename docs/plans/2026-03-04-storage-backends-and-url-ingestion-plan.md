# Storage Backends & URL-Based Image Ingestion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Abstract storage behind a `StorageBackend` protocol (S3, GCS, Local) and add a URL-based image ingestion endpoint.

**Architecture:** A `StorageBackend` protocol with three implementations replaces direct boto3 calls. Existing functions become thin wrappers. A new `POST /api/v1/images/ingest` endpoint accepts image URLs, downloads them via httpx, and feeds into the existing pipeline.

**Tech Stack:** Python 3.12, FastAPI, boto3, google-cloud-storage, httpx, SQLAlchemy async, Alembic, pytest

**Design doc:** `docs/plans/2026-03-04-storage-backends-and-url-ingestion-design.md`

---

### Task 1: Create the StorageBackend Protocol and Base Module

**Files:**
- Create: `src/pic/services/storage/__init__.py`
- Create: `src/pic/services/storage/base.py`
- Test: `tests/unit/test_storage_base.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_storage_base.py
"""Unit tests for StorageBackend protocol."""

import pytest

from pic.services.storage.base import StorageBackend, validate_storage_key


@pytest.mark.unit
class TestValidateStorageKey:
    def test_valid_inbox_key(self):
        validate_storage_key("images/photo.jpg")

    def test_valid_processed_key(self):
        validate_storage_key("processed/photo.jpg")

    def test_valid_thumbnail_key(self):
        validate_storage_key("thumbnails/abc.jpg")

    def test_valid_rejected_key(self):
        validate_storage_key("rejected/dup.jpg")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_storage_key("images/../etc/passwd")

    def test_rejects_unknown_prefix(self):
        with pytest.raises(ValueError, match="unexpected prefix"):
            validate_storage_key("secret/data.bin")


@pytest.mark.unit
class TestStorageBackendProtocol:
    def test_protocol_is_runtime_checkable(self):
        assert isinstance(StorageBackend, type)

    def test_non_conforming_class_fails_check(self):
        class NotABackend:
            pass

        assert not isinstance(NotABackend(), StorageBackend)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_storage_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pic.services.storage'`

**Step 3: Write minimal implementation**

```python
# src/pic/services/storage/__init__.py
"""Storage backend abstraction layer."""

from pic.services.storage.base import StorageBackend, validate_storage_key

__all__ = ["StorageBackend", "validate_storage_key"]
```

```python
# src/pic/services/storage/base.py
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_storage_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pic/services/storage/ tests/unit/test_storage_base.py
git commit -m "feat: add StorageBackend protocol and validate_storage_key"
```

---

### Task 2: Implement S3StorageBackend

**Files:**
- Create: `src/pic/services/storage/s3.py`
- Create: `tests/unit/test_storage_s3.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_storage_s3.py
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_storage_s3.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pic.services.storage.s3'`

**Step 3: Write minimal implementation**

```python
# src/pic/services/storage/s3.py
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_storage_s3.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pic/services/storage/s3.py tests/unit/test_storage_s3.py
git commit -m "feat: implement S3StorageBackend"
```

---

### Task 3: Implement GCSStorageBackend

**Files:**
- Create: `src/pic/services/storage/gcs.py`
- Create: `tests/unit/test_storage_gcs.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_storage_gcs.py
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
    with patch("pic.services.storage.gcs.storage.Client", return_value=client):
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_storage_gcs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pic.services.storage.gcs'`

**Step 3: Write minimal implementation**

```python
# src/pic/services/storage/gcs.py
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
        credentials = service_account.Credentials.from_service_account_info(creds_data)
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
        return blob.download_as_bytes()

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
        return blob.generate_signed_url(
            expiration=timedelta(seconds=expires_in),
            credentials=self._credentials,
            version="v4",
        )

    def exists(self, key: str) -> bool:
        blob = self._bucket.blob(key)
        return blob.exists()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_storage_gcs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pic/services/storage/gcs.py tests/unit/test_storage_gcs.py
git commit -m "feat: implement GCSStorageBackend"
```

---

### Task 4: Implement LocalStorageBackend

**Files:**
- Create: `src/pic/services/storage/local.py`
- Create: `tests/unit/test_storage_local.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_storage_local.py
"""Unit tests for LocalStorageBackend."""

import pytest

from pic.services.storage.base import StorageBackend


@pytest.fixture
def local_backend(tmp_path):
    from pic.services.storage.local import LocalStorageBackend

    return LocalStorageBackend(
        root_path=tmp_path,
        base_url="http://localhost:8000/files",
    )


@pytest.mark.unit
class TestLocalStorageBackend:
    def test_conforms_to_protocol(self, local_backend):
        assert isinstance(local_backend, StorageBackend)

    def test_upload_and_download(self, local_backend):
        local_backend.upload("images/test.jpg", b"image-data", "image/jpeg")
        result = local_backend.download("images/test.jpg")
        assert result == b"image-data"

    def test_delete(self, local_backend):
        local_backend.upload("images/test.jpg", b"data")
        local_backend.delete("images/test.jpg")
        assert not local_backend.exists("images/test.jpg")

    def test_move(self, local_backend):
        local_backend.upload("images/test.jpg", b"data")
        local_backend.move("images/test.jpg", "processed/test.jpg")
        assert not local_backend.exists("images/test.jpg")
        assert local_backend.exists("processed/test.jpg")
        assert local_backend.download("processed/test.jpg") == b"data"

    def test_list_objects(self, local_backend):
        local_backend.upload("images/a.jpg", b"a")
        local_backend.upload("images/b.jpg", b"b")
        local_backend.upload("processed/c.jpg", b"c")
        keys = local_backend.list_objects("images/")
        assert sorted(keys) == ["images/a.jpg", "images/b.jpg"]

    def test_get_url(self, local_backend):
        url = local_backend.get_url("processed/photo.jpg", expires_in=300)
        assert url == "http://localhost:8000/files/processed/photo.jpg"

    def test_exists_true(self, local_backend):
        local_backend.upload("images/test.jpg", b"data")
        assert local_backend.exists("images/test.jpg") is True

    def test_exists_false(self, local_backend):
        assert local_backend.exists("images/nope.jpg") is False

    def test_download_missing_raises(self, local_backend):
        with pytest.raises(FileNotFoundError):
            local_backend.download("images/nope.jpg")

    def test_rejects_path_traversal(self, local_backend):
        with pytest.raises(ValueError, match="path traversal"):
            local_backend.move("images/../etc/passwd", "processed/hacked")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_storage_local.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pic.services.storage.local'`

**Step 3: Write minimal implementation**

```python
# src/pic/services/storage/local.py
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_storage_local.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pic/services/storage/local.py tests/unit/test_storage_local.py
git commit -m "feat: implement LocalStorageBackend"
```

---

### Task 5: Add Storage Configuration and Factory

**Files:**
- Modify: `src/pic/config.py`
- Modify: `src/pic/services/storage/__init__.py`
- Create: `tests/unit/test_storage_factory.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_storage_factory.py
"""Unit tests for storage backend factory."""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestGetStorageBackend:
    def test_returns_s3_by_default(self):
        with patch("pic.services.storage.settings") as mock_settings:
            mock_settings.storage_backend = "s3"
            mock_settings.s3_bucket = "test"
            mock_settings.s3_endpoint_url = "https://s3.example.com"
            mock_settings.s3_access_key_id = "key"
            mock_settings.s3_secret_access_key = "secret"

            from pic.services.storage import _create_storage_backend

            backend = _create_storage_backend()
            from pic.services.storage.s3 import S3StorageBackend

            assert isinstance(backend, S3StorageBackend)

    def test_returns_local_backend(self, tmp_path):
        with patch("pic.services.storage.settings") as mock_settings:
            mock_settings.storage_backend = "local"
            mock_settings.local_storage_path = tmp_path
            mock_settings.local_storage_base_url = "http://localhost:8000/files"

            from pic.services.storage import _create_storage_backend

            backend = _create_storage_backend()
            from pic.services.storage.local import LocalStorageBackend

            assert isinstance(backend, LocalStorageBackend)

    def test_raises_on_unknown_backend(self):
        with patch("pic.services.storage.settings") as mock_settings:
            mock_settings.storage_backend = "azure"

            from pic.services.storage import _create_storage_backend

            with pytest.raises(ValueError, match="Unknown storage backend"):
                _create_storage_backend()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_storage_factory.py -v`
Expected: FAIL — `ImportError: cannot import name '_create_storage_backend'`

**Step 3: Add config settings**

Add these fields to `Settings` class in `src/pic/config.py` after the existing S3 block (line ~25):

```python
    # Storage backend selection
    storage_backend: str = "s3"  # "s3" | "gcs" | "local"

    # Google Cloud Storage (required when storage_backend=gcs)
    gcs_bucket: str = ""
    gcs_project_id: str = ""
    gcs_credentials_json: str = ""  # Service account JSON

    # Local filesystem storage (required when storage_backend=local)
    local_storage_path: Path = Path("data/storage")
    local_storage_base_url: str = ""  # e.g., http://localhost:8000/files
```

Add these validators to `Settings`:

```python
    @field_validator("storage_backend")
    @classmethod
    def validate_storage_backend(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"s3", "gcs", "local"}:
            raise ValueError("storage_backend must be one of: s3, gcs, local")
        return v

    @model_validator(mode="after")
    def validate_gcs_credentials(self) -> "Settings":
        if self.storage_backend == "gcs":
            if not self.gcs_bucket:
                raise ValueError("PIC_GCS_BUCKET is required when PIC_STORAGE_BACKEND=gcs")
            if not self.gcs_credentials_json:
                raise ValueError("PIC_GCS_CREDENTIALS_JSON is required when PIC_STORAGE_BACKEND=gcs")
        return self

    @model_validator(mode="after")
    def validate_local_storage_not_in_production(self) -> "Settings":
        if self.storage_backend == "local" and self.env == "production":
            raise ValueError("Local storage backend is not allowed in production")
        return self
```

**Step 4: Update factory in `__init__.py`**

```python
# src/pic/services/storage/__init__.py
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
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_storage_factory.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/pic/config.py src/pic/services/storage/__init__.py tests/unit/test_storage_factory.py
git commit -m "feat: add storage backend config and factory"
```

---

### Task 6: Refactor image_store.py to Delegate to StorageBackend

**Files:**
- Modify: `src/pic/services/image_store.py`
- Modify: `tests/conftest.py` — update `mock_s3` fixture
- Run: `tests/unit/test_image_store.py` — existing tests must still pass

**Step 1: Refactor `image_store.py`**

Replace the direct S3 functions with thin wrappers around `get_storage_backend()`. Keep `generate_thumbnail()`, `get_image_dimensions()`, presigned URL cache, and `S3ClientProtocol` (for backward compat).

Change these functions:

```python
# Replace upload_to_s3 body:
def upload_to_s3(file_bytes: bytes, s3_key: str, content_type: str = "image/jpeg") -> None:
    backend = get_storage_backend()
    backend.upload(s3_key, file_bytes, content_type)

# Replace download_from_s3 body:
def download_from_s3(s3_key: str) -> bytes:
    backend = get_storage_backend()
    return backend.download(s3_key)

# Replace move_s3_object body:
def move_s3_object(source_key: str, dest_key: str) -> None:
    backend = get_storage_backend()
    backend.move(source_key, dest_key)

# Replace list_s3_objects body:
def list_s3_objects(prefix: str) -> list[str]:
    backend = get_storage_backend()
    return backend.list_objects(prefix)

# Replace delete_s3_object body:
def delete_s3_object(s3_key: str) -> None:
    backend = get_storage_backend()
    backend.delete(s3_key)
```

Update `generate_presigned_url` to use backend:

```python
def generate_presigned_url(s3_key: str, expires_in: int | None = None) -> str:
    requested_expiry = settings.presigned_url_expiry if expires_in is None else expires_in
    bounded_expiry = max(1, min(requested_expiry, settings.presigned_url_max_expiry))
    return _generate_presigned_url_cached(s3_key, bounded_expiry)
```

The cached version `_generate_presigned_url_cached` should use `get_storage_backend().get_url()` instead of the raw S3 client.

Remove `get_s3_client()`, `_s3_retry` decorator, `_validate_s3_key()`, and `S3ClientProtocol` — they're now in `storage/s3.py`.

Keep: `generate_thumbnail()`, `get_image_dimensions()`, presigned URL cache logic.

**Step 2: Update `conftest.py` mock**

Update `mock_s3` fixture to mock the storage backend instead:

```python
@pytest.fixture
def mock_s3():
    """Mock storage backend."""
    mock_backend = MagicMock()
    with patch("pic.services.image_store.get_storage_backend", return_value=mock_backend):
        yield mock_backend
```

**Step 3: Run existing tests**

Run: `uv run pytest tests/unit/test_image_store.py -v`
Expected: PASS — existing tests still work with the mocked backend

**Step 4: Run all unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pic/services/image_store.py tests/conftest.py
git commit -m "refactor: delegate image_store.py to StorageBackend"
```

---

### Task 7: Add google-cloud-storage Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependency**

Add `"google-cloud-storage>=2.0"` to the `dependencies` list in `pyproject.toml` (after the existing Google entries).

**Step 2: Install**

Run: `uv sync`
Expected: Installs google-cloud-storage

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add google-cloud-storage"
```

---

### Task 8: Add source_url Column and DB Migration

**Files:**
- Modify: `src/pic/models/db.py`
- Modify: `src/pic/models/db.py` — add `URL_INGEST` to `JobType`
- Create: Alembic migration

**Step 1: Update the Image model**

Add after `file_size` field (line ~51 in `db.py`):

```python
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
```

**Step 2: Add URL_INGEST to JobType enum**

```python
class JobType(enum.StrEnum):
    INGEST = "ingest"
    CLUSTER_L1 = "cluster_l1"
    CLUSTER_L2 = "cluster_l2"
    CLUSTER_FULL = "cluster_full"
    PIPELINE = "pipeline"
    GDRIVE_SYNC = "gdrive_sync"
    URL_INGEST = "url_ingest"
```

**Step 3: Generate migration**

Run: `uv run alembic revision --autogenerate -m "add source_url to images and url_ingest job type"`

Review the generated migration file to ensure it:
- Adds `source_url` column (nullable String(2048))
- Updates the `jobtype` enum to include `url_ingest`

**Step 4: Update schemas**

Add to `ImageOut` in `src/pic/models/schemas.py`:

```python
    source_url: str | None = None
```

Add new schemas:

```python
from pydantic import HttpUrl

class UrlIngestRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=100)
    auto_pipeline: bool = False

class UrlIngestOut(BaseModel):
    job_id: str
    urls_submitted: int
```

**Step 5: Commit**

```bash
git add src/pic/models/db.py src/pic/models/schemas.py src/pic/migrations/
git commit -m "feat: add source_url column, URL_INGEST job type, and ingest schemas"
```

---

### Task 9: Implement URL Ingest Worker

**Files:**
- Create: `src/pic/worker/url_ingest.py`
- Create: `tests/unit/test_url_ingest.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_url_ingest.py
"""Unit tests for URL ingest worker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestDownloadFromUrl:
    @pytest.mark.asyncio
    async def test_downloads_valid_image_url(self):
        from pic.worker.url_ingest import download_from_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg", "content-length": "1024"}
        mock_response.content = b"fake-image-data"
        mock_response.raise_for_status = MagicMock()

        with patch("pic.worker.url_ingest.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await download_from_url("https://example.com/photo.jpg")
            assert result == b"fake-image-data"

    @pytest.mark.asyncio
    async def test_rejects_non_image_content_type(self):
        from pic.worker.url_ingest import download_from_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("pic.worker.url_ingest.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="not an image"):
                await download_from_url("https://example.com/page.html")

    @pytest.mark.asyncio
    async def test_rejects_oversized_response(self):
        from pic.worker.url_ingest import download_from_url

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/jpeg", "content-length": str(500 * 1024 * 1024)}
        mock_response.raise_for_status = MagicMock()

        with patch("pic.worker.url_ingest.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ValueError, match="exceeds size limit"):
                await download_from_url("https://example.com/huge.jpg")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_url_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pic.worker.url_ingest'`

**Step 3: Write implementation**

```python
# src/pic/worker/url_ingest.py
"""Worker task: Ingest images from URLs."""

import asyncio
import json
import logging
import os
from urllib.parse import urlparse

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pic.config import settings
from pic.core.constants import S3_PREFIX_INBOX
from pic.models.db import Image, Job, JobStatus
from pic.services.image_store import upload_to_s3
from pic.worker.image_processing import check_content_duplicate, compute_content_hash, insert_image_record

logger = logging.getLogger(__name__)

_URL_DOWNLOAD_TIMEOUT = 30  # seconds per URL


async def download_from_url(url: str) -> bytes:
    """Download an image from a URL with validation."""
    max_bytes = settings.max_image_download_mb * 1024 * 1024

    async with httpx.AsyncClient(follow_redirects=True, timeout=_URL_DOWNLOAD_TIMEOUT) as client:
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"URL content is not an image (content-type: {content_type})")

        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError(
                f"Image exceeds size limit ({int(content_length)} > {max_bytes} bytes)"
            )

        data = response.content
        if len(data) > max_bytes:
            raise ValueError(f"Image exceeds size limit ({len(data)} > {max_bytes} bytes)")

        return data


def _filename_from_url(url: str) -> str:
    """Extract a safe filename from a URL."""
    parsed = urlparse(url)
    basename = os.path.basename(parsed.path) or "image.jpg"
    return basename.replace("..", "_")[:256]


async def run_url_ingest(job_id: str, urls: list[str], auto_pipeline: bool = False) -> None:
    """Download images from URLs, deduplicate, and store."""
    from pic.core.database import async_session

    async with async_session() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.RUNNING)
        )
        await db.commit()

        succeeded = 0
        duplicates = 0
        failed = 0
        errors: list[dict[str, str]] = []
        new_image_ids: list[str] = []
        seen_hashes: set[str] = set()

        semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)

        async def _process_url(url: str) -> None:
            nonlocal succeeded, duplicates, failed
            async with semaphore:
                try:
                    image_bytes = await download_from_url(url)
                except Exception as exc:
                    failed += 1
                    errors.append({"url": url, "reason": str(exc)})
                    logger.warning("Failed to download %s: %s", url, exc)
                    return

                content_hash = compute_content_hash(image_bytes)

                if content_hash in seen_hashes:
                    duplicates += 1
                    logger.info("Intra-batch duplicate URL: %s", url)
                    return

                if await check_content_duplicate(db, content_hash):
                    duplicates += 1
                    logger.info("Duplicate of existing image from URL: %s", url)
                    return

                seen_hashes.add(content_hash)

                filename = _filename_from_url(url)
                import uuid

                s3_key = f"{S3_PREFIX_INBOX}{uuid.uuid4()}_{filename}"

                upload_to_s3(image_bytes, s3_key)

                image_id = await insert_image_record(
                    db,
                    filename=filename,
                    s3_key=s3_key,
                    content_hash=content_hash,
                    file_size=len(image_bytes),
                )
                if image_id:
                    # Update source_url on the newly created record
                    await db.execute(
                        update(Image).where(Image.id == image_id).values(source_url=url)
                    )
                    new_image_ids.append(image_id)
                    succeeded += 1
                else:
                    duplicates += 1

        # Process URLs concurrently
        await asyncio.gather(*[_process_url(url) for url in urls])
        await db.commit()

        result = {
            "total": len(urls),
            "succeeded": succeeded,
            "duplicates": duplicates,
            "failed": failed,
            "new_image_ids": new_image_ids,
            "errors": errors,
        }

        from datetime import datetime, timezone

        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=JobStatus.COMPLETED,
                progress=1.0,
                result=json.dumps(result),
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        logger.info("URL ingest job %s complete: %s", job_id, result)

    if auto_pipeline and new_image_ids:
        logger.info("Auto-pipeline triggered for %d new images", len(new_image_ids))
        # Trigger pipeline via Modal (reuse existing dispatch)
        from pic.services.modal_dispatch import submit_pipeline_job

        try:
            await submit_pipeline_job(job_id)
        except Exception:
            logger.exception("Failed to trigger auto-pipeline after URL ingest")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_url_ingest.py -v`
Expected: PASS

**Step 5: Add httpx to dependencies**

`httpx` is already in dev dependencies. Add to main dependencies in `pyproject.toml`:

```
    "httpx>=0.27",
```

**Step 6: Commit**

```bash
git add src/pic/worker/url_ingest.py tests/unit/test_url_ingest.py pyproject.toml
git commit -m "feat: implement URL ingest worker"
```

---

### Task 10: Add URL Ingest API Endpoint

**Files:**
- Modify: `src/pic/api/images.py`
- Modify: `src/pic/api/router.py` (if needed — images router already included)
- Modify: `src/pic/services/modal_dispatch.py`

**Step 1: Add Modal dispatch function for URL ingest**

Add to `src/pic/services/modal_dispatch.py`:

```python
MODAL_FN_URL_INGEST = "run_url_ingest"

@_retry
async def submit_url_ingest_job(job_id: str, params: dict[str, object] | None = None) -> str:
    """Trigger Modal function for URL-based image ingest. Returns Modal call ID."""
    params_json = json.dumps(params) if params else None
    return _spawn_modal_job(MODAL_FN_URL_INGEST, job_id, params_json)
```

**Step 2: Add the endpoint to `images.py`**

```python
from pic.api.deps import create_and_dispatch_job
from pic.core.rate_limit import limiter
from pic.models.db import JobType
from pic.models.schemas import UrlIngestRequest, UrlIngestOut
from pic.services.modal_dispatch import submit_url_ingest_job
from starlette.requests import Request

@router.post(
    "/ingest",
    response_model=UrlIngestOut,
    status_code=202,
    summary="Ingest images from URLs",
    description="Download images from provided URLs, deduplicate, and store. Returns a job ID for tracking.",
)
@limiter.limit(settings.job_trigger_rate_limit)
async def ingest_from_urls(
    request: Request,
    body: UrlIngestRequest,
    db: AsyncSession = Depends(get_db),
) -> UrlIngestOut:
    urls = [str(u) for u in body.urls]
    params = {"urls": urls, "auto_pipeline": body.auto_pipeline}

    job = await create_and_dispatch_job(
        db,
        job_type=JobType.URL_INGEST,
        dispatch_fn=submit_url_ingest_job,
        params=params,
    )
    return UrlIngestOut(job_id=job.id, urls_submitted=len(urls))
```

**Step 3: Run linter**

Run: `uv run ruff check src/pic/api/images.py src/pic/services/modal_dispatch.py --fix`
Expected: No errors

**Step 4: Commit**

```bash
git add src/pic/api/images.py src/pic/services/modal_dispatch.py
git commit -m "feat: add POST /images/ingest endpoint for URL-based ingestion"
```

---

### Task 11: Mount Local Storage File Server

**Files:**
- Modify: `src/pic/main.py`

**Step 1: Add static file mount for local backend**

Add after the router includes in `main.py`:

```python
# Serve local storage files when using local backend
if settings.storage_backend == "local":
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/files",
        StaticFiles(directory=str(settings.local_storage_path)),
        name="local_storage",
    )
    logger.info("Mounted local storage at /files -> %s", settings.local_storage_path)
```

**Step 2: Run linter**

Run: `uv run ruff check src/pic/main.py --fix`

**Step 3: Commit**

```bash
git add src/pic/main.py
git commit -m "feat: mount local file server when storage_backend=local"
```

---

### Task 12: Update Worker Modules to Use StorageBackend

**Files:**
- Modify: `src/pic/worker/pipeline_discover.py`
- Modify: `src/pic/worker/pipeline_ingest.py`
- Modify: `src/pic/worker/ingest.py`
- Modify: `src/pic/worker/image_processing.py`

**Step 1: Update imports**

In all four files, replace:
```python
from pic.services.image_store import download_from_s3, upload_to_s3, move_s3_object, list_s3_objects
```
with:
```python
from pic.services.image_store import download_from_s3, upload_to_s3, move_s3_object, list_s3_objects
```

No actual changes needed here — since `image_store.py` functions are now thin wrappers (Task 6), all existing worker code automatically uses the configured backend. This task verifies that nothing broke.

**Step 2: Run all unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: PASS

**Step 3: Run linter on worker modules**

Run: `uv run ruff check src/pic/worker/ --fix`

**Step 4: Commit (only if changes were needed)**

```bash
git add src/pic/worker/
git commit -m "refactor: verify workers use storage backend via image_store wrappers"
```

---

### Task 13: Integration Test for URL Ingest Endpoint

**Files:**
- Create: `tests/integration/test_images_url_ingest.py`

**Step 1: Write integration test**

```python
# tests/integration/test_images_url_ingest.py
"""Integration tests for URL-based image ingestion."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestUrlIngestEndpoint:
    async def test_ingest_returns_202_with_job_id(self, client: AsyncClient):
        """POST /images/ingest should accept URLs and return a job ID."""
        response = await client.post(
            "/api/v1/images/ingest",
            json={"urls": ["https://example.com/photo.jpg"]},
        )
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["urls_submitted"] == 1

    async def test_ingest_rejects_empty_urls(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/images/ingest",
            json={"urls": []},
        )
        assert response.status_code == 422

    async def test_ingest_rejects_too_many_urls(self, client: AsyncClient):
        urls = [f"https://example.com/img{i}.jpg" for i in range(101)]
        response = await client.post(
            "/api/v1/images/ingest",
            json={"urls": urls},
        )
        assert response.status_code == 422
```

Note: The integration test for `POST /images/ingest` needs the Modal dispatch mocked. Check how existing integration tests handle this in `tests/integration/conftest.py` and follow the same pattern.

**Step 2: Run integration tests**

Run: `uv run pytest tests/integration/test_images_url_ingest.py -v`
Expected: PASS (with Modal dispatch mocked)

**Step 3: Commit**

```bash
git add tests/integration/test_images_url_ingest.py
git commit -m "test: add integration tests for URL ingest endpoint"
```

---

### Task 14: Update Project Documentation

**Files:**
- Modify: `README.md` — document new storage backends and URL ingest endpoint
- Modify: `CHANGELOG.md` — add entries for both features
- Modify: `ROADMAP.md` — mark items as completed
- Modify: `docs/agents.md` (if exists) — update architecture notes
- Modify: `docs/architecture*.md` or `docs/deployment*.md` (if exists) — add storage backend config

**Step 1: Update ROADMAP.md**

Mark "URL-Based Image Ingestion" and "Configurable Storage Backends" as completed with links to the design doc.

**Step 2: Update CHANGELOG.md**

Add under a new section:

```markdown
## [Unreleased]

### Added
- **Configurable Storage Backends**: Support for S3 (existing), Google Cloud Storage, and local filesystem via `PIC_STORAGE_BACKEND` env var
- **URL-Based Image Ingestion**: New `POST /api/v1/images/ingest` endpoint accepts image URLs for batch download and ingestion
- `source_url` field on Image model to track URL-ingested images
- `URL_INGEST` job type for tracking URL ingestion jobs

### Changed
- Refactored `image_store.py` to delegate to pluggable `StorageBackend` protocol
- Storage key validation moved from S3-specific to backend-agnostic
```

**Step 3: Update README.md**

Add a "Storage Backends" section documenting:
- `PIC_STORAGE_BACKEND` (s3/gcs/local)
- Per-backend env vars
- URL ingest endpoint usage example

**Step 4: Update technical_debt.md** (if exists)

Note that `upload_to_s3`/`download_from_s3` function names are now misleading — they're backend-agnostic wrappers. Consider renaming in a future refactor.

**Step 5: Commit**

```bash
git add README.md CHANGELOG.md ROADMAP.md docs/
git commit -m "docs: update documentation for storage backends and URL ingestion"
```

---

### Task 15: Final Verification

**Step 1: Run full test suite**

Run: `uv run pytest tests/unit/ -v --tb=short`
Expected: All PASS

**Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors

**Step 3: Run type checker**

Run: `uv run mypy src/pic/`
Expected: No new errors

**Step 4: Verify import chain**

Run: `uv run python -c "from pic.services.storage import get_storage_backend; print('OK')"`
Expected: `OK`

---

Plan complete and saved to `docs/plans/2026-03-04-storage-backends-and-url-ingestion-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?
