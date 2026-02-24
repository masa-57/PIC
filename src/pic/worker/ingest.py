"""Worker task: Process an uploaded image (compute hashes + DINOv2 embedding)."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pic.core.constants import S3_PREFIX_INBOX, S3_PREFIX_PROCESSED
from pic.core.database import async_session
from pic.models.db import Image
from pic.services.embedding import compute_embedding, compute_hashes
from pic.services.hash_utils import hex_to_bitstring
from pic.services.image_store import download_from_s3, move_s3_object

logger = logging.getLogger(__name__)


async def run_ingest(image_id: str) -> None:
    """Download image from S3, compute pHash + DINOv2 embedding, update DB."""
    async with async_session() as db:
        # Load image record
        result = await db.execute(select(Image).where(Image.id == image_id))
        image = result.scalar_one_or_none()
        if not image:
            logger.error("Image %s not found in database", image_id)
            return

        logger.info("Processing image %s (%s)", image_id, image.s3_key)

        # Download from S3
        image_bytes = download_from_s3(image.s3_key)

        # Compute perceptual hashes
        phash, dhash = compute_hashes(image_bytes)
        image.phash = phash
        image.dhash = dhash
        image.phash_bits = hex_to_bitstring(phash)
        logger.info("Computed hashes for %s: phash=%s", image_id, phash[:16])

        # Compute DINOv2 embedding
        embedding = compute_embedding(image_bytes)
        image.embedding = embedding
        image.has_embedding = 1  # type: ignore[assignment]  # DB column is Integer(0/1)
        logger.info("Computed embedding for %s (dim=%d)", image_id, len(embedding))

        await db.commit()
        logger.info("Image %s processing complete", image_id)

        # Move processed image from images/ to processed/ prefix
        await _move_to_processed(image, db)


async def _move_to_processed(image: Image, db: AsyncSession) -> None:
    """Move the S3 object to processed/ and update the DB key. Best-effort."""
    source_key = image.s3_key
    if not source_key.startswith(S3_PREFIX_INBOX):
        return

    dest_key = S3_PREFIX_PROCESSED + source_key.removeprefix(S3_PREFIX_INBOX)
    try:
        move_s3_object(source_key, dest_key)
        image.s3_key = dest_key
        await db.commit()
        logger.info("Moved %s → %s", source_key, dest_key)
    except Exception:
        logger.exception("Failed to move %s to processed/ (non-fatal)", source_key)
