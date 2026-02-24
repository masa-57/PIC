"""Worker task: Run the full L1 + L2 clustering pipeline."""

import json
import logging

from nic.core.constants import ADVISORY_LOCK_ID
from nic.services.clustering_pipeline import run_full_clustering
from nic.worker.helpers import mark_job_completed, worker_lifecycle

logger = logging.getLogger(__name__)


async def run_cluster(job_id: str, params_json: str | None = None) -> None:
    """Run the full clustering pipeline: L1 (near-duplicate) then L2 (semantic)."""
    params = json.loads(params_json) if params_json else {}

    async with worker_lifecycle(ADVISORY_LOCK_ID, job_id, "Clustering") as db:
        if db is None:
            return
        stats = await run_full_clustering(db, params)
        await mark_job_completed(db, job_id, dict(stats))
