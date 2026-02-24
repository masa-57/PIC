import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nic.api.deps import PaginationParams, build_pagination_links, get_db, get_or_404
from nic.models.db import Job, JobStatus
from nic.models.schemas import JobListOut, JobOut, ProblemDetail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobOut,
    responses={404: {"model": ProblemDetail, "description": "Job not found"}},
)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    job = await get_or_404(db, Job, job_id, "Job not found")
    return JobOut.model_validate(job)


@router.get(
    "",
    response_model=JobListOut,
    summary="List jobs",
    description="Returns a paginated list of jobs sorted by creation date descending. Optionally filter by status.",
)
async def list_jobs(
    pagination: PaginationParams = Depends(),
    status: JobStatus | None = Query(None, description="Filter by job status (PENDING, RUNNING, COMPLETED, FAILED)"),
    db: AsyncSession = Depends(get_db),
) -> JobListOut:
    query = select(Job)
    count_query = select(func.count()).select_from(Job)

    if status is not None:
        query = query.where(Job.status == status)
        count_query = count_query.where(Job.status == status)

    query = query.order_by(Job.created_at.desc()).offset(pagination.offset).limit(pagination.limit)

    result = await db.execute(query)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    return JobListOut(
        items=[JobOut.model_validate(j) for j in result.scalars().all()],
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/jobs", total, pagination.offset, pagination.limit),
    )
