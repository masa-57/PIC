"""Worker task: Run the full L1 + L2 clustering pipeline."""

import json
import logging

from pic.core.constants import ADVISORY_LOCK_ID
from pic.services.clustering_pipeline import run_full_clustering
from pic.worker.helpers import LockNotAcquiredError, mark_job_completed, worker_lifecycle

logger = logging.getLogger(__name__)


async def run_cluster(job_id: str, params_json: str | None = None) -> None:
    """Run the full clustering pipeline: L1 (near-duplicate) then L2 (semantic)."""
    params = json.loads(params_json) if params_json else {}

    try:
        async with worker_lifecycle(ADVISORY_LOCK_ID, job_id, "Clustering") as db:
            stats = await run_full_clustering(db, params)
            await mark_job_completed(db, job_id, dict(stats))
    except LockNotAcquiredError:
        return
