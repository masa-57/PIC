"""Worker task: Ingest images from URLs."""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pic.config import settings

logger = logging.getLogger(__name__)

_URL_DOWNLOAD_TIMEOUT = 30  # seconds per URL


@dataclass(frozen=True)
class DownloadResult:
    url: str
    image_bytes: bytes | None = None
    error: str | None = None


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


async def _download_urls(urls: list[str]) -> list[DownloadResult]:
    """Download URLs concurrently without sharing DB session state across tasks."""
    semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)

    async def _download_one(url: str) -> DownloadResult:
        async with semaphore:
            try:
                image_bytes = await download_from_url(url)
            except Exception as exc:
                logger.warning("Failed to download %s: %s", url, exc)
                return DownloadResult(url=url, error=str(exc))
            return DownloadResult(url=url, image_bytes=image_bytes)

    return list(await asyncio.gather(*[_download_one(url) for url in urls]))


async def _queue_auto_pipeline_job(db: AsyncSession) -> tuple[str | None, str | None]:
    """Create and dispatch a separate pipeline job for auto-pipeline mode."""
    from pic.models.db import Job, JobStatus, JobType
    from pic.services.modal_dispatch import submit_pipeline_job

    pipeline_job_id = str(uuid.uuid4())
    db.add(Job(id=pipeline_job_id, type=JobType.PIPELINE, status=JobStatus.PENDING))
    await db.commit()

    try:
        modal_call_id = await submit_pipeline_job(pipeline_job_id)
    except Exception:
        logger.exception("Failed to trigger auto-pipeline job %s", pipeline_job_id)
        await db.execute(
            update(Job)
            .where(Job.id == pipeline_job_id)
            .values(
                status=JobStatus.FAILED,
                error="Failed to dispatch job to Modal",
                completed_at=datetime.now(UTC),
            )
        )
        await db.commit()
        return None, "Failed to dispatch auto-pipeline job"

    if modal_call_id:
        await db.execute(update(Job).where(Job.id == pipeline_job_id).values(modal_call_id=modal_call_id))
        await db.commit()

    return pipeline_job_id, None


async def run_url_ingest(job_id: str, urls: list[str], auto_pipeline: bool = False) -> None:
    """Download images from URLs, deduplicate, and store."""
    from pic.core.constants import S3_PREFIX_INBOX
    from pic.core.database import async_session
    from pic.models.db import Image, Job, JobStatus
    from pic.services.image_store import upload_to_s3
    from pic.worker.image_processing import check_content_duplicate, compute_content_hash, insert_image_record

    try:
        async with async_session() as db:
            await db.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.RUNNING))
            await db.commit()

        downloads = await _download_urls(urls)

        succeeded = 0
        duplicates = 0
        failed = 0
        errors: list[dict[str, str]] = []
        new_image_ids: list[str] = []
        seen_hashes: set[str] = set()
        pipeline_job_id: str | None = None
        pipeline_job_error: str | None = None

        async with async_session() as db:
            for download in downloads:
                if download.error is not None:
                    failed += 1
                    errors.append({"url": download.url, "reason": download.error})
                    continue

                image_bytes = download.image_bytes
                if image_bytes is None:
                    failed += 1
                    errors.append({"url": download.url, "reason": "Download returned no data"})
                    continue

                content_hash = compute_content_hash(image_bytes)

                if content_hash in seen_hashes:
                    duplicates += 1
                    logger.info("Intra-batch duplicate URL: %s", download.url)
                    continue

                if await check_content_duplicate(db, content_hash):
                    duplicates += 1
                    logger.info("Duplicate of existing image from URL: %s", download.url)
                    continue

                seen_hashes.add(content_hash)

                filename = _filename_from_url(download.url)
                s3_key = f"{S3_PREFIX_INBOX}{uuid.uuid4()}_{filename}"

                await asyncio.to_thread(upload_to_s3, image_bytes, s3_key)

                image_id = await insert_image_record(
                    db,
                    filename=filename,
                    s3_key=s3_key,
                    content_hash=content_hash,
                    file_size=len(image_bytes),
                )
                if image_id:
                    await db.execute(update(Image).where(Image.id == image_id).values(source_url=download.url))
                    new_image_ids.append(image_id)
                    succeeded += 1
                else:
                    duplicates += 1

            await db.commit()

            if auto_pipeline and new_image_ids:
                logger.info("Auto-pipeline requested for %d new images", len(new_image_ids))
                pipeline_job_id, pipeline_job_error = await _queue_auto_pipeline_job(db)

            result: dict[str, object] = {
                "total": len(urls),
                "succeeded": succeeded,
                "duplicates": duplicates,
                "failed": failed,
                "new_image_ids": new_image_ids,
                "errors": errors,
            }
            if auto_pipeline:
                result["auto_pipeline_requested"] = True
            if pipeline_job_id is not None:
                result["pipeline_job_id"] = pipeline_job_id
            if pipeline_job_error is not None:
                result["pipeline_job_error"] = pipeline_job_error

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
    except Exception as exc:
        logger.exception("URL ingest job %s failed", job_id)
        async with async_session() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=JobStatus.FAILED,
                    error=str(exc),
                    completed_at=datetime.now(UTC),
                )
            )
            await db.commit()
        raise
