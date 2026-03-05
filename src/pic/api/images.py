import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from pic.api.deps import PaginationParams, build_pagination_links, create_and_dispatch_job, get_db, get_or_404
from pic.config import settings
from pic.core.rate_limit import limiter
from pic.models.db import Image, JobType
from pic.models.schemas import ImageFileOut, ImageListOut, ImageOut, ProblemDetail, UrlIngestOut, UrlIngestRequest
from pic.services.image_store import generate_presigned_url
from pic.services.modal_dispatch import submit_url_ingest_job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["images"])


@router.get(
    "",
    response_model=ImageListOut,
    summary="List images",
    description="Returns a paginated list of images. Supports filtering by L1 group and embedding status.",
)
async def list_images(
    pagination: PaginationParams = Depends(),
    l1_group_id: int | None = Query(None, description="Filter by L1 group ID"),
    has_embedding: bool | None = Query(
        None, description="Filter by embedding status (true = has embedding, false = missing)"
    ),
    db: AsyncSession = Depends(get_db),
) -> ImageListOut:
    query = select(Image)
    count_query = select(func.count()).select_from(Image)

    if l1_group_id is not None:
        query = query.where(Image.l1_group_id == l1_group_id)
        count_query = count_query.where(Image.l1_group_id == l1_group_id)
    if has_embedding is not None:
        query = query.where(Image.has_embedding == (1 if has_embedding else 0))
        count_query = count_query.where(Image.has_embedding == (1 if has_embedding else 0))

    query = query.order_by(Image.created_at.desc()).offset(pagination.offset).limit(pagination.limit)

    result = await db.execute(query)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    return ImageListOut(
        items=[ImageOut.model_validate(img) for img in result.scalars().all()],
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/images", total, pagination.offset, pagination.limit),
    )


@router.post(
    "/ingest",
    response_model=UrlIngestOut,
    status_code=202,
    summary="Ingest images from URLs",
    description="Download images from provided URLs, deduplicate, and store. Returns a job ID for tracking.",
)
@limiter.limit(settings.job_trigger_rate_limit)
async def ingest_from_urls(
    request: Request,
    body: UrlIngestRequest,
    db: AsyncSession = Depends(get_db),
) -> UrlIngestOut:
    urls = [str(u) for u in body.urls]
    params = {"urls": urls, "auto_pipeline": body.auto_pipeline}

    job = await create_and_dispatch_job(
        db,
        job_type=JobType.URL_INGEST,
        dispatch_fn=submit_url_ingest_job,
        params=params,
    )
    return UrlIngestOut(job_id=job.id, urls_submitted=len(urls))


@router.get(
    "/{image_id}",
    response_model=ImageOut,
    responses={404: {"model": ProblemDetail, "description": "Image not found"}},
)
async def get_image(
    image_id: str,
    db: AsyncSession = Depends(get_db),
) -> ImageOut:
    image = await get_or_404(db, Image, image_id, "Image not found")
    return ImageOut.model_validate(image)


@router.get(
    "/{image_id}/file",
    response_model=ImageFileOut,
    responses={404: {"model": ProblemDetail, "description": "Image not found"}},
)
async def get_image_file(
    image_id: str,
    thumbnail: bool = Query(False, description="Return thumbnail URL instead of full image"),
    db: AsyncSession = Depends(get_db),
) -> ImageFileOut:
    image = await get_or_404(db, Image, image_id, "Image not found")
    s3_key = image.s3_thumbnail_key if thumbnail and image.s3_thumbnail_key else image.s3_key
    presigned_url = generate_presigned_url(s3_key)
    return ImageFileOut(presigned_url=presigned_url, expires_in=settings.presigned_url_expiry)
