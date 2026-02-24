import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nic.api.deps import PaginationParams, build_pagination_links, create_and_dispatch_job, get_db
from nic.config import settings
from nic.core.rate_limit import limiter
from nic.models.db import Image, JobType, L1Group, L2Cluster
from nic.models.schemas import (
    ClusterHierarchyOut,
    ClusterRunRequest,
    JobOut,
    L1GroupBriefOut,
    L1GroupListOut,
    L1GroupOut,
    L2ClusterHierarchyItemOut,
    L2ClusterListOut,
    L2ClusterOut,
    L2ClusterSummary,
    ProblemDetail,
    VisualizationOut,
    VisualizationPoint,
)
from nic.services.cluster_visualization import generate_visualization_html
from nic.services.modal_dispatch import submit_cluster_job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clusters", tags=["clusters"])
# Separate router for browser-accessible HTML pages
view_router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.post(
    "/run",
    response_model=JobOut,
    status_code=202,
    responses={
        429: {"model": ProblemDetail, "description": "Too many pending jobs"},
        503: {"model": ProblemDetail, "description": "Failed to dispatch job"},
    },
)
@limiter.limit(settings.job_trigger_rate_limit)
async def run_clustering(
    request: Request,
    response: Response,
    body: ClusterRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> JobOut:
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

    job = await create_and_dispatch_job(db, JobType.CLUSTER_FULL, submit_cluster_job, params or None)
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return JobOut.model_validate(job)


@router.get(
    "",
    response_model=ClusterHierarchyOut,
    summary="Get cluster hierarchy",
    description="Returns L2 clusters with their L1 groups, plus unclustered L1 groups. "
    "Both sets are independently paginated.",
)
async def get_hierarchy(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> ClusterHierarchyOut:
    # Paginated L2 clusters with eagerly loaded groups (no nested images)
    l2_result = await db.execute(
        select(L2Cluster)
        .options(selectinload(L2Cluster.groups))
        .order_by(L2Cluster.total_images.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    l2_clusters = l2_result.scalars().all()

    total_l2_result = await db.execute(select(func.count()).select_from(L2Cluster))
    total_l2 = total_l2_result.scalar_one()

    # Unclustered groups use independent pagination (not shared with L2)
    unclustered_result = await db.execute(
        select(L1Group)
        .where(L1Group.l2_cluster_id.is_(None))
        .order_by(L1Group.member_count.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    unclustered_groups = unclustered_result.scalars().all()

    total_unclustered_result = await db.execute(
        select(func.count()).select_from(L1Group).where(L1Group.l2_cluster_id.is_(None))
    )
    total_unclustered = total_unclustered_result.scalar_one()

    total_images_result = await db.execute(select(func.count()).select_from(Image))
    total_images = total_images_result.scalar_one()

    total_l1_result = await db.execute(select(func.count()).select_from(L1Group))
    total_l1 = total_l1_result.scalar_one()

    return ClusterHierarchyOut(
        l2_clusters=[L2ClusterHierarchyItemOut.model_validate(c) for c in l2_clusters],
        unclustered_groups=[L1GroupBriefOut.model_validate(g) for g in unclustered_groups],
        total_l2_clusters=total_l2,
        total_unclustered_groups=total_unclustered,
        total_l1_groups=total_l1,
        total_images=total_images,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/clusters", total_l2, pagination.offset, pagination.limit),
    )


@router.get(
    "/level2",
    response_model=L2ClusterListOut,
    summary="List L2 clusters",
    description="Returns a paginated list of L2 clusters sorted by total image count descending.",
)
async def list_l2_clusters(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> L2ClusterListOut:
    result = await db.execute(
        select(L2Cluster).order_by(L2Cluster.total_images.desc()).offset(pagination.offset).limit(pagination.limit)
    )
    total_result = await db.execute(select(func.count()).select_from(L2Cluster))
    total = total_result.scalar_one()

    return L2ClusterListOut(
        items=[L2ClusterSummary.model_validate(c) for c in result.scalars().all()],
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/clusters/level2", total, pagination.offset, pagination.limit),
    )


@router.get(
    "/level2/{cluster_id}",
    response_model=L2ClusterOut,
    responses={404: {"model": ProblemDetail, "description": "L2 cluster not found"}},
)
async def get_l2_cluster(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
) -> L2ClusterOut:
    result = await db.execute(
        select(L2Cluster)
        .where(L2Cluster.id == cluster_id)
        .options(selectinload(L2Cluster.groups).selectinload(L1Group.images))
    )
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(status_code=404, detail="L2 cluster not found")
    return L2ClusterOut.model_validate(cluster)


@router.get(
    "/level1",
    response_model=L1GroupListOut,
    summary="List L1 groups",
    description="Returns a paginated list of L1 groups sorted by member count descending. "
    "Optionally filter by L2 cluster.",
)
async def list_l1_groups(
    pagination: PaginationParams = Depends(),
    l2_cluster_id: int | None = Query(None, description="Filter by parent L2 cluster ID"),
    db: AsyncSession = Depends(get_db),
) -> L1GroupListOut:
    query = select(L1Group)
    count_query = select(func.count()).select_from(L1Group)

    if l2_cluster_id is not None:
        query = query.where(L1Group.l2_cluster_id == l2_cluster_id)
        count_query = count_query.where(L1Group.l2_cluster_id == l2_cluster_id)

    query = query.order_by(L1Group.member_count.desc()).offset(pagination.offset).limit(pagination.limit)

    result = await db.execute(query)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    return L1GroupListOut(
        items=[L1GroupBriefOut.model_validate(g) for g in result.scalars().all()],
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/clusters/level1", total, pagination.offset, pagination.limit),
    )


@router.get(
    "/level1/{group_id}",
    response_model=L1GroupOut,
    responses={404: {"model": ProblemDetail, "description": "L1 group not found"}},
)
async def get_l1_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
) -> L1GroupOut:
    result = await db.execute(select(L1Group).where(L1Group.id == group_id).options(selectinload(L1Group.images)))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="L1 group not found")
    return L1GroupOut.model_validate(group)


@router.get("/visualization", response_model=VisualizationOut)
async def get_visualization(
    db: AsyncSession = Depends(get_db),
) -> VisualizationOut:
    points: list[VisualizationPoint] = []
    # Join with Image to get the centroid's actual l1_group_id
    cluster_result = await db.execute(
        select(L2Cluster, Image.l1_group_id)
        .outerjoin(Image, L2Cluster.centroid_image_id == Image.id)
        .where(L2Cluster.viz_x.isnot(None))
    )
    for cluster, l1_group_id in cluster_result.all():
        if cluster.centroid_image_id and cluster.viz_x is not None and cluster.viz_y is not None:
            points.append(
                VisualizationPoint(
                    image_id=cluster.centroid_image_id,
                    l1_group_id=l1_group_id,
                    l2_cluster_id=cluster.id,
                    x=cluster.viz_x,
                    y=cluster.viz_y,
                )
            )

    return VisualizationOut(points=points)


@view_router.get(
    "/view",
    response_class=HTMLResponse,
    summary="Visual cluster browser",
    description="Returns a self-contained HTML page showing L2 → L1 → Image hierarchy.",
)
async def view_clusters(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Browser-friendly cluster visualization page."""
    html = await generate_visualization_html(db, url_expiry=3600)
    return HTMLResponse(content=html)
