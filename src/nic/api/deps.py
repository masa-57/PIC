import logging
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nic.config import settings
from nic.core.database import async_session
from nic.models.db import Job, JobStatus, JobType

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


@dataclass
class PaginationParams:
    offset: int = Query(0, ge=0, le=settings.max_pagination_offset, description="Number of items to skip")  # noqa: B008
    limit: int = Query(50, ge=1, le=200, description="Maximum number of items to return (1-200)")  # noqa: B008


async def get_or_404(
    db: AsyncSession,
    model: type[T],
    id_value: Any,  # noqa: ANN401
    detail: str = "Not found",
) -> T:
    """Load a single record by primary key or raise 404."""
    result = await db.execute(select(model).where(model.id == id_value))  # type: ignore[attr-defined]
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail=detail)
    return obj


async def create_and_dispatch_job(
    db: AsyncSession,
    job_type: JobType,
    dispatch_fn: Callable[..., Any],
    params: dict[str, Any] | None = None,
) -> Job:
    """Create a job record, dispatch to Modal, and handle failures."""
    pending_result = await db.execute(
        select(func.count()).select_from(Job).where(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
    )
    pending_count = int(pending_result.scalar_one())
    if pending_count >= settings.job_queue_max_pending:
        raise HTTPException(
            status_code=429,
            detail=f"Job queue is full ({pending_count} pending/running); try again later",
        )

    job_id = str(uuid.uuid4())
    job = Job(id=job_id, type=job_type, status=JobStatus.PENDING)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    try:
        modal_call_id = await dispatch_fn(job_id, params)
    except Exception:
        logger.exception("Failed to dispatch %s job %s to Modal", job_type.value, job_id)
        await db.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.FAILED, error="Failed to dispatch job to Modal")
        )
        await db.commit()
        raise HTTPException(status_code=503, detail="Failed to dispatch job to compute backend") from None

    # Store Modal call ID for failure monitoring
    if modal_call_id:
        await db.execute(update(Job).where(Job.id == job_id).values(modal_call_id=modal_call_id))
        await db.commit()
        await db.refresh(job)

    return job


def build_pagination_links(
    path: str,
    total: int,
    offset: int,
    limit: int,
    extra_params: dict[str, str] | None = None,
) -> Any:
    """Build pagination navigation links for list responses."""
    from nic.models.schemas import PaginationLinks

    def _url(o: int) -> str:
        params = {"offset": str(o), "limit": str(limit)}
        if extra_params:
            params.update(extra_params)
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{path}?{qs}"

    next_offset = offset + limit
    prev_offset = max(0, offset - limit)
    last_page_offset = max(0, ((total - 1) // limit) * limit) if total > 0 else 0

    return PaginationLinks.model_validate(
        {
            "self": _url(offset),
            "next": _url(next_offset) if next_offset < total else None,
            "prev": _url(prev_offset) if offset > 0 else None,
            "first": _url(0),
            "last": _url(last_page_offset) if total > 0 else None,
        }
    )
