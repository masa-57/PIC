"""Store uploaded image files in the storage inbox, where the pipeline picks them up."""

import asyncio
import logging
import mimetypes
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from pic.config import settings
from pic.core.constants import IMAGE_EXTENSIONS, S3_PREFIX_INBOX
from pic.services.image_store import upload_to_s3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadedFile:
    name: str  # as sent by the browser; may include a relative folder path
    data: bytes


@dataclass
class UploadResult:
    stored: list[str] = field(default_factory=list)  # inbox keys
    skipped: list[dict[str, str]] = field(default_factory=list)  # {"name": ..., "reason": ...}


def inbox_key(name: str) -> str:
    """Inbox key for an uploaded file: its base name only, with a unique prefix so names never collide."""
    base = os.path.basename(name.replace("\\", "/")).replace("..", "_").strip() or "image"
    return f"{S3_PREFIX_INBOX}{uuid.uuid4().hex[:12]}_{base[:200]}"


async def store_uploads(files: Sequence[UploadedFile]) -> UploadResult:
    """Write supported, non-empty images within the size limit to the inbox; report the rest."""
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    result = UploadResult()
    for upload in files:
        extension = os.path.splitext(upload.name)[1].lower()
        if extension not in IMAGE_EXTENSIONS:
            result.skipped.append({"name": upload.name, "reason": "not a supported image type"})
            continue
        if not upload.data:
            result.skipped.append({"name": upload.name, "reason": "empty file"})
            continue
        if len(upload.data) > max_bytes:
            result.skipped.append({"name": upload.name, "reason": f"larger than {settings.max_upload_size_mb} MB"})
            continue
        key = inbox_key(upload.name)
        content_type = mimetypes.guess_type(upload.name)[0] or "application/octet-stream"
        try:
            await asyncio.to_thread(upload_to_s3, upload.data, key, content_type=content_type)
        except Exception:
            logger.exception("Failed to store uploaded file %s", upload.name)
            result.skipped.append({"name": upload.name, "reason": "could not be stored"})
            continue
        result.stored.append(key)
    return result
