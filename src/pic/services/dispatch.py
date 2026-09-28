"""Route new jobs to the configured worker backend."""

import logging
from typing import Any

from pic.config import settings
from pic.models.db import JobType

logger = logging.getLogger(__name__)

# Job types the local pic-worker can run. Must match RUNNERS in pic.worker.local_runner.
LOCAL_JOB_TYPES: frozenset[JobType] = frozenset(
    {JobType.CLUSTER_FULL, JobType.PIPELINE, JobType.URL_INGEST, JobType.GDRIVE_SYNC}
)


async def dispatch_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str | None:
    """Hand a PENDING job to the worker backend.

    Returns the Modal call ID for the ``modal`` backend. Returns ``None`` for the
    ``local`` backend: the job stays PENDING until a ``pic-worker`` process claims it.
    """
    if settings.worker_backend == "modal":
        # Imported lazily so the API does not need Modal installed or configured by default.
        from pic.services.modal_dispatch import spawn_modal_job

        return await spawn_modal_job(job_type, job_id, params)

    if job_type not in LOCAL_JOB_TYPES:
        raise ValueError(f"Local worker cannot run job type {job_type.value}")
    logger.info("Queued %s job %s for the local worker", job_type.value, job_id)
    return None
