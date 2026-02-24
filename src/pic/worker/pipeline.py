"""Worker task: Full pipeline — discover images in R2, deduplicate, ingest, cluster.

This is the orchestrator module. Business logic lives in:
- pipeline_discover: S3 discovery and content deduplication
- pipeline_ingest: Batch download, embed, and process
- image_processing: Shared image-processing helpers
"""

import json
import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pic.core.constants import ADVISORY_LOCK_ID
from pic.models.db import Job
from pic.services.clustering_pipeline import run_full_clustering
from pic.worker.helpers import LockNotAcquiredError, mark_job_completed, worker_lifecycle
from pic.worker.pipeline_discover import phase_discover_and_dedup
from pic.worker.pipeline_ingest import phase_batch_ingest

logger = logging.getLogger(__name__)


async def run_pipeline(job_id: str, params_json: str | None = None) -> None:
    """Full pipeline: discover → deduplicate → ingest → cluster."""
    params = json.loads(params_json) if params_json else {}

    try:
        async with worker_lifecycle(ADVISORY_LOCK_ID, job_id, "Pipeline") as db:
            await _run_full_pipeline(db, job_id, params)
    except LockNotAcquiredError:
        return


async def _run_full_pipeline(db: AsyncSession, job_id: str, params: dict[str, int]) -> None:
    # ── Phase 0: Discover & Deduplicate ──
    new_image_ids, phase0_stats = await phase_discover_and_dedup(db, job_id)

    await db.execute(update(Job).where(Job.id == job_id).values(progress=0.1))
    await db.commit()

    # ── Phase 1: Batch Ingest ──
    ingest_stats = await phase_batch_ingest(db, job_id, new_image_ids)

    await db.execute(update(Job).where(Job.id == job_id).values(progress=0.5))
    await db.commit()

    # ── Phase 2: Clustering (L1 + L2) ──
    cluster_stats = await run_full_clustering(db, params)

    # ── Complete ──
    summary = {
        "total_discovered": phase0_stats["discovered"],
        "duplicates_skipped": phase0_stats["duplicates"],
        "ingest_errors": len(ingest_stats["failed_image_ids"]) + len(ingest_stats["skipped_download_image_ids"]),
        "images_ingested": ingest_stats["ingested"],
        "failed_image_ids": ingest_stats["failed_image_ids"],
        "skipped_download_image_ids": ingest_stats["skipped_download_image_ids"],
        "retried_success_count": ingest_stats["retried_success_count"],
        **cluster_stats,
    }

    await mark_job_completed(db, job_id, summary)
    logger.info("Pipeline complete: %s", summary)
