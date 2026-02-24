"""Pipeline Phase 0: S3 discovery and content deduplication."""

import asyncio
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pic.config import settings
from pic.core.constants import IMAGE_EXTENSIONS, S3_PREFIX_INBOX, S3_PREFIX_PROCESSED, S3_PREFIX_REJECTED
from pic.services.image_store import download_from_s3, list_s3_objects, move_s3_object
from pic.worker.image_processing import check_content_duplicate, compute_content_hash, insert_image_record

logger = logging.getLogger(__name__)


async def download_s3_concurrent(s3_keys: list[str], max_concurrency: int) -> list[tuple[str, bytes | None]]:
    """Download multiple S3 objects concurrently using a semaphore.

    Returns list of (s3_key, image_bytes_or_None) in the same order as input.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _download_one(key: str) -> tuple[str, bytes | None]:
        async with semaphore:
            try:
                data = await asyncio.to_thread(download_from_s3, key)
            except Exception:
                logger.exception("Failed to download %s, skipping", key)
                return key, None
            else:
                return key, data

    tasks = [_download_one(key) for key in s3_keys]
    return list(await asyncio.gather(*tasks))


async def phase_discover_and_dedup(db: AsyncSession, job_id: str) -> tuple[list[str], dict[str, int]]:
    """Scan R2 images/ prefix, deduplicate, create DB records for new images."""
    from pic.models.db import Image

    s3_keys = list_s3_objects(S3_PREFIX_INBOX)
    s3_keys = [k for k in s3_keys if os.path.splitext(k)[1].lower() in IMAGE_EXTENSIONS]

    logger.info("Discovered %d image files in images/ prefix", len(s3_keys))

    if not s3_keys:
        return [], {"discovered": 0, "duplicates": 0}

    # Fast pre-download dedup by key: skip files already tracked as either
    # images/<name> (pending ingest) or processed/<name> (already ingested).
    dedup_candidates = {
        k for s3_key in s3_keys for k in (s3_key, S3_PREFIX_PROCESSED + s3_key.removeprefix(S3_PREFIX_INBOX))
    }
    existing_keys_result = await db.execute(select(Image.s3_key).where(Image.s3_key.in_(dedup_candidates)))
    existing_keys = set(existing_keys_result.scalars().all())

    keys_to_download: list[str] = []
    duplicates = 0
    for s3_key in s3_keys:
        processed_key = S3_PREFIX_PROCESSED + s3_key.removeprefix(S3_PREFIX_INBOX)
        if s3_key in existing_keys or processed_key in existing_keys:
            logger.info("Skipping already-ingested key before download: %s", s3_key)
            _move_to_rejected(s3_key)
            duplicates += 1
            continue
        keys_to_download.append(s3_key)

    # Download all images concurrently
    downloaded = await download_s3_concurrent(keys_to_download, settings.max_concurrent_downloads)

    max_bytes = settings.max_image_download_mb * 1024 * 1024
    new_image_ids: list[str] = []
    seen_hashes: set[str] = set()

    for s3_key, image_bytes in downloaded:
        if image_bytes is None:
            continue

        if len(image_bytes) > max_bytes:
            logger.warning("Image %s exceeds size limit (%d MB), rejecting", s3_key, settings.max_image_download_mb)
            _move_to_rejected(s3_key)
            continue

        content_hash = compute_content_hash(image_bytes)

        # Intra-batch dedup
        if content_hash in seen_hashes:
            logger.info("Intra-batch duplicate: %s (hash=%s…)", s3_key, content_hash[:12])
            _move_to_rejected(s3_key)
            duplicates += 1
            continue

        # DB dedup
        if await check_content_duplicate(db, content_hash):
            logger.info("Duplicate of existing image: %s (hash=%s…)", s3_key, content_hash[:12])
            _move_to_rejected(s3_key)
            duplicates += 1
            continue

        seen_hashes.add(content_hash)

        filename = os.path.basename(s3_key)
        image_id = await insert_image_record(
            db,
            filename=filename,
            s3_key=s3_key,
            content_hash=content_hash,
            file_size=len(image_bytes),
        )
        if image_id:
            new_image_ids.append(image_id)
        else:
            logger.info("Concurrent duplicate: %s (hash=%s…)", s3_key, content_hash[:12])
            _move_to_rejected(s3_key)
            duplicates += 1

    await db.commit()
    logger.info("Phase 0 complete: %d new, %d duplicates", len(new_image_ids), duplicates)

    return new_image_ids, {"discovered": len(s3_keys), "duplicates": duplicates}


def _move_to_rejected(s3_key: str) -> None:
    """Move a duplicate file to rejected/ prefix. Best-effort."""
    dest_key = S3_PREFIX_REJECTED + s3_key.removeprefix(S3_PREFIX_INBOX)
    try:
        move_s3_object(s3_key, dest_key)
    except Exception:
        logger.exception("Failed to move %s to rejected/ (non-fatal)", s3_key)
