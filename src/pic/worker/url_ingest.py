"""Worker task: Ingest images from URLs."""

import asyncio
import json
import logging
import os
from urllib.parse import urlparse

import httpx

from pic.config import settings

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
            raise ValueError(f"Image exceeds size limit ({int(content_length)} > {max_bytes} bytes)")

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
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import update

    from pic.core.constants import S3_PREFIX_INBOX
    from pic.core.database import async_session
    from pic.models.db import Image, Job, JobStatus
    from pic.services.image_store import upload_to_s3
    from pic.worker.image_processing import check_content_duplicate, compute_content_hash, insert_image_record

    async with async_session() as db:
        await db.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.RUNNING))
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
                    await db.execute(update(Image).where(Image.id == image_id).values(source_url=url))
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

        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=JobStatus.COMPLETED,
                progress=1.0,
                result=json.dumps(result),
                completed_at=datetime.now(UTC),
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
