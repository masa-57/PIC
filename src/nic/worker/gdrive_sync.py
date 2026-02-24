"""Worker task: Google Drive → R2 sync with inline processing.

This is the orchestrator module. Business logic lives in:
- gdrive_download: GDrive-specific download, dedup, and batch processing
- image_processing: Shared image-processing helpers
"""

import json
import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from nic.config import settings
from nic.core.constants import ADVISORY_LOCK_ID
from nic.models.db import Job
from nic.services.clustering_pipeline import run_full_clustering
from nic.services.gdrive import build_drive_service, get_or_create_processed_folder, list_image_files
from nic.worker.gdrive_download import process_batch
from nic.worker.helpers import mark_job_completed, worker_lifecycle

logger = logging.getLogger(__name__)


async def run_gdrive_sync(job_id: str, params_json: str | None = None) -> None:
    """Run the full GDrive → R2 sync + process + cluster pipeline."""
    params = json.loads(params_json) if params_json else {}

    async with worker_lifecycle(ADVISORY_LOCK_ID, job_id, "GDrive sync") as db:
        if db is None:
            return
        await _sync_process_and_cluster(db, job_id, params)


async def _sync_process_and_cluster(
    db: AsyncSession,
    job_id: str,
    params: dict[str, int],
) -> None:
    """Phase 1: Download + dedup + process. Phase 2: Cluster."""
    # ── Phase 1: Download, dedup, process (progress 0.0 → 0.8) ──
    service = build_drive_service(settings.gdrive_service_account_json)
    gdrive_files = list_image_files(service, settings.gdrive_folder_id)

    if not gdrive_files:
        logger.info("No new files in Google Drive, completing job %s", job_id)
        await mark_job_completed(
            db,
            job_id,
            {
                "files_discovered": 0,
                "files_uploaded": 0,
                "duplicates_skipped": 0,
                "files_errored": 0,
                "total_bytes": 0,
            },
        )
        return

    processed_folder_id = get_or_create_processed_folder(service, settings.gdrive_folder_id)

    files_uploaded = 0
    duplicates_skipped = 0
    files_errored = 0
    total_bytes = 0
    max_bytes = settings.max_image_download_mb * 1024 * 1024
    batch_size = max(1, settings.embedding_batch_size)

    for batch_start in range(0, len(gdrive_files), batch_size):
        batch_files = gdrive_files[batch_start : batch_start + batch_size]
        batch_result = await process_batch(
            db,
            service,
            batch_files,
            processed_folder_id,
            max_bytes,
        )
        files_uploaded += batch_result["uploaded"]
        duplicates_skipped += batch_result["duplicates"]
        files_errored += batch_result["errored"]
        total_bytes += batch_result["bytes"]

        # Update progress (0.0 to 0.8 range for download+process phase)
        progress = 0.8 * min((batch_start + len(batch_files)) / len(gdrive_files), 1.0)
        await db.execute(update(Job).where(Job.id == job_id).values(progress=progress))
        await db.commit()

    logger.info(
        "Phase 1 complete: %d uploaded, %d duplicates, %d errors from %d files",
        files_uploaded,
        duplicates_skipped,
        files_errored,
        len(gdrive_files),
    )

    # ── Phase 2: Clustering (progress 0.8 → 1.0) ──
    if files_uploaded > 0:
        cluster_stats = await run_full_clustering(db, params)
    else:
        from nic.models.schemas import ClusteringStats

        cluster_stats = ClusteringStats(total_images=0, l1_groups=0, l2_clusters=0, l2_noise_groups=0)

    summary: dict[str, object] = {
        "files_discovered": len(gdrive_files),
        "files_uploaded": files_uploaded,
        "duplicates_skipped": duplicates_skipped,
        "files_errored": files_errored,
        "total_bytes": total_bytes,
        **cluster_stats,
    }
    await mark_job_completed(db, job_id, summary)
    logger.info("GDrive sync complete: %s", summary)
