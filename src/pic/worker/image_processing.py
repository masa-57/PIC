"""Shared image-processing helpers used by pipeline and gdrive_sync workers."""

import hashlib
import io
import logging
import os
import uuid

from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from nic.core.constants import S3_PREFIX_INBOX, S3_PREFIX_PROCESSED, S3_PREFIX_THUMBNAILS
from nic.models.db import Image
from nic.services.embedding import compute_embeddings_batch, compute_hashes
from nic.services.hash_utils import hex_to_bitstring
from nic.services.image_store import generate_thumbnail, get_image_dimensions, move_s3_object, upload_to_s3

logger = logging.getLogger(__name__)


async def check_content_duplicate(db: AsyncSession, content_hash: str) -> bool:
    """Check if an image with the given SHA256 content hash already exists in DB."""
    result = await db.execute(select(Image.id).where(Image.content_hash == content_hash).limit(1))
    return result.scalar_one_or_none() is not None


def compute_content_hash(image_bytes: bytes) -> str:
    """Compute SHA256 hex digest of image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


def process_single_image(img: Image, image_bytes: bytes, embedding: list[float]) -> bool:
    """Process a single image: compute hashes, dimensions, thumbnail, move to processed/.

    Updates the Image ORM object in-place. Returns True on success, False on failure.
    Used by both the R2 pipeline (pipeline_ingest) and GDrive sync workers.

    Opens the image once and passes the PIL Image to hashing, dimension, and thumbnail
    functions to avoid redundant PIL.Image.open() calls.
    """
    try:
        with PILImage.open(io.BytesIO(image_bytes)) as pil_img:
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")  # type: ignore[assignment]

            phash, dhash = compute_hashes(pil_img)
            img.phash = phash
            img.phash_bits = hex_to_bitstring(phash)
            img.dhash = dhash
            img.embedding = embedding
            img.has_embedding = 1  # type: ignore[assignment]  # DB column is Integer(0/1)

            img.width, img.height = get_image_dimensions(pil_img)

            thumb_bytes = generate_thumbnail(pil_img)
            thumb_key = f"{S3_PREFIX_THUMBNAILS}{img.id}.jpg"
            upload_to_s3(thumb_bytes, thumb_key, content_type="image/jpeg")
            img.s3_thumbnail_key = thumb_key

        # Move to processed/ — only update DB key on success.
        dest_key = S3_PREFIX_PROCESSED + img.s3_key.removeprefix(S3_PREFIX_INBOX)
        try:
            move_s3_object(img.s3_key, dest_key)
            img.s3_key = dest_key
        except Exception:
            logger.warning("Failed to move %s to processed/, keeping original key", img.s3_key, exc_info=True)
    except Exception:
        logger.exception("Failed to process image %s, skipping", img.id)
        return False
    else:
        return True


def retry_single_image_ingest(img: Image, image_bytes: bytes) -> bool:
    """Retry ingest for one image when batch embedding/processing fails.

    Attempts up to 2 retries of embedding + processing for a single image.
    """
    for attempt in (1, 2):
        try:
            embedding = compute_embeddings_batch([image_bytes])[0]
        except Exception:
            logger.warning("Retry %d failed to compute embedding for image %s", attempt, img.id, exc_info=True)
            continue
        if process_single_image(img, image_bytes, embedding):
            return True
    return False


async def insert_image_record(
    db: AsyncSession,
    *,
    filename: str,
    s3_key: str,
    content_hash: str,
    file_size: int,
    phash: str | None = None,
    phash_bits: str | None = None,
    dhash: str | None = None,
    embedding: list[float] | None = None,
    has_embedding: int = 0,
    width: int | None = None,
    height: int | None = None,
    s3_thumbnail_key: str | None = None,
) -> str | None:
    """Insert a new Image record with ON CONFLICT dedup. Returns image_id or None if duplicate."""
    image_id = str(uuid.uuid4())
    values: dict[str, object] = {
        "id": image_id,
        "filename": filename,
        "s3_key": s3_key,
        "content_hash": content_hash,
        "file_size": file_size,
        "has_embedding": 1 if has_embedding else 0,
    }
    if phash is not None:
        values["phash"] = phash
    if phash_bits is not None:
        values["phash_bits"] = phash_bits
    if dhash is not None:
        values["dhash"] = dhash
    if embedding is not None:
        values["embedding"] = embedding
    if width is not None:
        values["width"] = width
    if height is not None:
        values["height"] = height
    if s3_thumbnail_key is not None:
        values["s3_thumbnail_key"] = s3_thumbnail_key

    stmt = pg_insert(Image).values(**values).on_conflict_do_nothing(index_elements=["content_hash"])
    result = await db.execute(stmt)
    if (result.rowcount or 0) > 0:  # type: ignore[attr-defined]
        return image_id
    return None


def safe_filename(raw_name: str, fallback_id: str) -> str:
    """Sanitize a filename, falling back to a UUID-based name."""
    name = os.path.basename(raw_name).replace("..", "_")
    if not name:
        name = f"unnamed_{fallback_id[:8]}.jpg"
    return name
