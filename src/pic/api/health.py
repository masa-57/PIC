"""Health check endpoints."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text

from pic.core.auth import verify_api_key
from pic.core.database import async_session, engine, get_pool_status
from pic.core.rate_limit import limiter
from pic.models.db import Job, JobStatus
from pic.models.schemas import DetailedHealthOut, HealthOut, PoolStatusOut
from pic.worker.helpers import check_modal_job_status, sweep_stale_jobs

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthOut)
@limiter.limit("30/minute")
async def health_check(request: Request) -> HealthOut:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("Database health check failed")
        db_status = "error"

    return HealthOut(
        status="ok" if db_status == "connected" else "degraded",
        database=db_status,
    )


@router.get("/health/detailed", response_model=DetailedHealthOut, dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def detailed_health_check(request: Request) -> DetailedHealthOut:
    """Detailed health check for external monitoring (Railway, UptimeRobot)."""
    # Database check
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("Database health check failed")
        db_status = "error"

    # Recent job failures (last hour) + sweep stale RUNNING jobs + check Modal
    failed_count = 0
    stale_swept = 0
    try:
        async with async_session() as db:
            stale_swept = await sweep_stale_jobs(db)

            # Proactively detect Modal function failures
            try:
                await check_modal_job_status(db)
            except Exception:
                logger.warning("Modal job status check failed (non-fatal)", exc_info=True)

            one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
            result = await db.execute(
                select(func.count())
                .select_from(Job)
                .where(Job.status == JobStatus.FAILED, Job.completed_at >= one_hour_ago)
            )
            failed_count = result.scalar_one()
    except Exception:
        logger.warning("Failed to query recent job failures", exc_info=True)

    overall = "ok"
    if db_status != "connected":
        overall = "degraded"
    elif failed_count > 5:
        overall = "warning"

    return DetailedHealthOut(
        status=overall,
        database=db_status,
        recent_failed_jobs=failed_count,
        stale_jobs_swept=stale_swept,
        connection_pool=PoolStatusOut(**get_pool_status()),
    )
