"""Pipeline Phase 1: Batch download, embed, and process images."""

import logging
from typing import TypedDict

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pic.config import settings
from pic.models.db import Image, Job
from pic.services.embedding import compute_embeddings_batch
from pic.worker.image_processing import process_single_image, retry_single_image_ingest
from pic.worker.pipeline_discover import download_s3_concurrent

logger = logging.getLogger(__name__)


class IngestStats(TypedDict):
    ingested: int
    failed_image_ids: list[str]
    skipped_download_image_ids: list[str]
    retried_success_count: int


async def download_batch(batch_images: list[Image]) -> tuple[list[tuple[Image, bytes]], list[str]]:
    """Download image bytes for a batch concurrently.

    Returns (downloaded_images, skipped_image_ids).
    """
    max_bytes = settings.max_image_download_mb * 1024 * 1024
    keys = [img.s3_key for img in batch_images]
    downloaded = await download_s3_concurrent(keys, settings.max_concurrent_downloads)

    results: list[tuple[Image, bytes]] = []
    skipped: list[str] = []
    for img, (_, image_bytes) in zip(batch_images, downloaded, strict=True):
        if image_bytes is None:
            skipped.append(img.id)
            continue
        if len(image_bytes) > max_bytes:
            logger.warning("Image %s exceeds size limit, skipping", img.s3_key)
            skipped.append(img.id)
            continue
        results.append((img, image_bytes))
    return results, skipped


async def phase_batch_ingest(db: AsyncSession, job_id: str, image_ids: list[str]) -> IngestStats:
    """Compute hashes, embeddings, thumbnails for new images."""
    if not image_ids:
        logger.info("No new images to ingest")
        return {
            "ingested": 0,
            "failed_image_ids": [],
            "skipped_download_image_ids": [],
            "retried_success_count": 0,
        }

    result = await db.execute(select(Image).where(Image.id.in_(image_ids)))
    images = list(result.scalars().all())

    ingested = 0
    failed_image_ids: list[str] = []
    skipped_download_image_ids: list[str] = []
    retried_success_count = 0
    batch_size = max(1, settings.embedding_batch_size)
    for batch_start in range(0, len(images), batch_size):
        batch_images = images[batch_start : batch_start + batch_size]
        downloaded, skipped = await download_batch(batch_images)
        skipped_download_image_ids.extend(skipped)

        if not downloaded:
            continue

        valid_images, batch_bytes_list = zip(*downloaded, strict=True)

        try:
            embeddings = compute_embeddings_batch(list(batch_bytes_list))
        except Exception:
            logger.exception("Failed to compute embeddings for batch starting at %d", batch_start)
            for img, image_bytes in zip(valid_images, batch_bytes_list, strict=True):
                if retry_single_image_ingest(img, image_bytes):
                    ingested += 1
                    retried_success_count += 1
                else:
                    failed_image_ids.append(img.id)
            continue

        for img, image_bytes, embedding in zip(valid_images, batch_bytes_list, embeddings, strict=True):
            if process_single_image(img, image_bytes, embedding):
                ingested += 1
            else:
                if retry_single_image_ingest(img, image_bytes):
                    ingested += 1
                    retried_success_count += 1
                else:
                    failed_image_ids.append(img.id)

        # Update progress (0.1 to 0.5 range for ingest phase)
        progress = 0.1 + 0.4 * min((batch_start + len(batch_images)) / len(images), 1.0)
        await db.execute(update(Job).where(Job.id == job_id).values(progress=progress))
        await db.commit()

        logger.info(
            "Ingested batch %d-%d of %d (%d successful)",
            batch_start,
            batch_start + len(batch_images),
            len(images),
            ingested,
        )

    logger.info("Phase 1 complete: %d/%d images ingested", ingested, len(images))
    return {
        "ingested": ingested,
        "failed_image_ids": failed_image_ids,
        "skipped_download_image_ids": skipped_download_image_ids,
        "retried_success_count": retried_success_count,
    }
