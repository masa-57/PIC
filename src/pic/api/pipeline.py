"""Pipeline API: trigger full ingest + clustering pipeline."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pic.api.deps import create_and_dispatch_job, get_db
from pic.models.db import JobType
from pic.models.schemas import ClusterRunRequest, JobOut, ProblemDetail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post(
    "/run",
    response_model=JobOut,
    status_code=202,
    responses={
        429: {"model": ProblemDetail, "description": "Too many pending jobs"},
        503: {"model": ProblemDetail, "description": "Failed to dispatch job"},
    },
)
async def run_pipeline(
    response: Response,
    body: ClusterRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    """Trigger the full pipeline: discover images in R2, deduplicate, ingest, and cluster."""
    params: dict[str, Any] = {}
    if body:
        if body.l1_min_cluster_size is not None:
            params["l1_min_cluster_size"] = body.l1_min_cluster_size
        if body.l1_min_samples is not None:
            params["l1_min_samples"] = body.l1_min_samples
        if body.l1_cluster_selection_epsilon is not None:
            params["l1_cluster_selection_epsilon"] = body.l1_cluster_selection_epsilon
        if body.l2_min_cluster_size is not None:
            params["l2_min_cluster_size"] = body.l2_min_cluster_size
        if body.l2_min_samples is not None:
            params["l2_min_samples"] = body.l2_min_samples

    job = await create_and_dispatch_job(db, JobType.PIPELINE, params or None)
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return JobOut.model_validate(job)
