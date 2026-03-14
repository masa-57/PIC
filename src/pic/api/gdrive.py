"""Google Drive sync API: manual trigger for GDrive → R2 sync."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pic.api.deps import create_and_dispatch_job, get_db
from pic.config import settings
from pic.core.rate_limit import limiter
from pic.models.db import JobType
from pic.models.schemas import JobOut
from pic.services.modal_dispatch import submit_gdrive_sync_job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gdrive", tags=["gdrive"])


@router.post("/sync", response_model=JobOut, status_code=202)
@limiter.limit(settings.job_trigger_rate_limit)
async def trigger_gdrive_sync(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    """Manually trigger a Google Drive → R2 sync job."""
    if not settings.gdrive_folder_id or not settings.gdrive_service_account_json:
        raise HTTPException(status_code=400, detail="Google Drive sync not configured")

    job = await create_and_dispatch_job(db, JobType.GDRIVE_SYNC, submit_gdrive_sync_job, None)
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return JobOut.model_validate(job)
