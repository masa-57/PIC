"""GDrive download, deduplication, and per-batch processing logic."""

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from pic.core.constants import S3_PREFIX_PROCESSED, S3_PREFIX_THUMBNAILS
from pic.services.embedding import compute_embeddings_batch, compute_hashes
from pic.services.gdrive import GDriveFile, download_file, move_file_to_folder
from pic.services.hash_utils import hex_to_bitstring
from pic.services.image_store import generate_thumbnail, get_image_dimensions, upload_to_s3
from pic.worker.image_processing import (
    check_content_duplicate,
    compute_content_hash,
    insert_image_record,
    safe_filename,
)

logger = logging.getLogger(__name__)


async def download_and_dedup(
    db: AsyncSession,
    service: object,
    batch_files: list[GDriveFile],
    processed_folder_id: str,
    max_bytes: int,
) -> tuple[list[tuple[GDriveFile, bytes, str]], int, int]:
    """Download files in parallel and deduplicate. Returns (valid_files, duplicates, errored)."""

    async def _download_one(gf: GDriveFile) -> tuple[GDriveFile, bytes | None]:
        try:
            data = await asyncio.to_thread(download_file, service, gf.id)
        except Exception:
            logger.exception("Failed to download %s from GDrive, skipping", gf.name)
            return gf, None
        return gf, data

    download_results = await asyncio.gather(*[_download_one(gf) for gf in batch_files])

    valid_files: list[tuple[GDriveFile, bytes, str]] = []
    duplicates = 0
    errored = 0
    for gfile, file_bytes in download_results:
        if file_bytes is None:
            errored += 1
            continue

        if len(file_bytes) > max_bytes:
            logger.warning("File %s exceeds size limit (%d MB), skipping", gfile.name, max_bytes // (1024 * 1024))
            _move_to_processed_safe(service, gfile, processed_folder_id)
            errored += 1
            continue

        content_hash = compute_content_hash(file_bytes)
        if await check_content_duplicate(db, content_hash):
            logger.info("Duplicate content: %s (hash=%s…)", gfile.name, content_hash[:12])
            _move_to_processed_safe(service, gfile, processed_folder_id)
            duplicates += 1
            continue

        valid_files.append((gfile, file_bytes, content_hash))

    return valid_files, duplicates, errored


async def process_batch(
    db: AsyncSession,
    service: object,
    batch_files: list[GDriveFile],
    processed_folder_id: str,
    max_bytes: int,
) -> dict[str, int]:
    """Process a batch of files: download, dedup, embed, upload. Returns batch stats."""
    uploaded = 0
    total_bytes = 0

    valid_files, duplicates, errored = await download_and_dedup(
        db, service, batch_files, processed_folder_id, max_bytes
    )

    if not valid_files:
        return {"uploaded": uploaded, "duplicates": duplicates, "errored": errored, "bytes": total_bytes}

    # GPU batch embedding
    batch_bytes_list = [fb for _, fb, _ in valid_files]
    try:
        embeddings = compute_embeddings_batch(batch_bytes_list)
        del batch_bytes_list
    except Exception:
        logger.exception("Failed to compute embeddings for batch, skipping %d files", len(valid_files))
        errored += len(valid_files)
        return {"uploaded": uploaded, "duplicates": duplicates, "errored": errored, "bytes": total_bytes}

    # Process each file (hashes, thumbnail, upload, DB record)
    for (gfile, file_bytes, content_hash), embedding in zip(valid_files, embeddings, strict=True):
        try:
            image_id = str(uuid.uuid4())

            phash, dhash = compute_hashes(file_bytes)
            width, height = get_image_dimensions(file_bytes)

            # Upload original to R2 processed/ (skip images/ inbox)
            fname = safe_filename(gfile.name, image_id)
            s3_key = f"{S3_PREFIX_PROCESSED}{fname}"
            upload_to_s3(file_bytes, s3_key)

            # Generate + upload thumbnail
            thumb_bytes = generate_thumbnail(file_bytes)
            thumb_key = f"{S3_PREFIX_THUMBNAILS}{image_id}.jpg"
            upload_to_s3(thumb_bytes, thumb_key, content_type="image/jpeg")

            # Create DB record (ON CONFLICT defends against race conditions)
            inserted_id = await insert_image_record(
                db,
                filename=gfile.name,
                s3_key=s3_key,
                s3_thumbnail_key=thumb_key,
                content_hash=content_hash,
                file_size=len(file_bytes),
                phash=phash,
                phash_bits=hex_to_bitstring(phash),
                dhash=dhash,
                embedding=embedding,
                has_embedding=1,
                width=width,
                height=height,
            )

            if inserted_id:
                uploaded += 1
                total_bytes += len(file_bytes)
            else:
                logger.info("Concurrent duplicate: %s (hash=%s…)", gfile.name, content_hash[:12])
                duplicates += 1

            _move_to_processed_safe(service, gfile, processed_folder_id)

        except Exception:
            logger.exception("Failed to process %s, skipping", gfile.name)
            errored += 1

    await db.commit()
    return {"uploaded": uploaded, "duplicates": duplicates, "errored": errored, "bytes": total_bytes}


def _move_to_processed_safe(service: object, gfile: GDriveFile, processed_folder_id: str) -> None:
    """Move a file to the processed folder in GDrive. Best-effort, non-fatal."""
    try:
        move_file_to_folder(service, gfile.id, gfile.parent_id, processed_folder_id)
    except Exception:
        logger.warning("Failed to move %s to processed/ in GDrive (non-fatal)", gfile.name, exc_info=True)
