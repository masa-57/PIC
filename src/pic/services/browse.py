"""Read models for the web UI: small, paged queries that return plain dataclasses."""

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pic.config import settings
from pic.models.db import Image, Job, JobStatus, JobType, L1Group, L2Cluster
from pic.services.image_store import generate_presigned_url

CLUSTER_PAGE = 24
GROUP_PAGE = 20
THUMBS_PER_CARD = 4
THUMBS_PER_GROUP = 12
UNCLUSTERED = "unclustered"
_CLUSTERING_JOB_TYPES = (
    JobType.PIPELINE,
    JobType.CLUSTER_FULL,
    JobType.CLUSTER_L1,
    JobType.CLUSTER_L2,
    JobType.GDRIVE_SYNC,
)
_ACTIVE = (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True)
class Thumb:
    id: str
    filename: str
    thumb_url: str
    full_url: str


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    offset: int
    limit: int

    @property
    def next_offset(self) -> int:
        return self.offset + self.limit

    @property
    def has_more(self) -> bool:
        return self.next_offset < self.total


@dataclass(frozen=True)
class ClusterCard:
    ref: str
    title: str
    total_images: int
    group_count: int
    thumbnails: list[Thumb]


@dataclass(frozen=True)
class GroupRow:
    id: int
    member_count: int
    product_id: int | None
    images: list[Thumb]

    @property
    def more(self) -> int:
        return max(0, self.member_count - len(self.images))


def image_url(key: str) -> str:
    """Browser URL for a stored object. Local storage uses a relative path so CSP 'self' always matches."""
    if settings.storage_backend == "local":
        return f"/files/{key}"
    return generate_presigned_url(key)


def thumb_for(image_id: str, filename: str, s3_key: str, thumbnail_key: str | None) -> Thumb:
    full = image_url(s3_key)
    return Thumb(
        id=image_id, filename=filename, thumb_url=image_url(thumbnail_key) if thumbnail_key else full, full_url=full
    )


def _group_scope(ref: str) -> object | None:
    """SQL filter for the groups of a cluster ref, or None if the ref is not valid."""
    if ref == UNCLUSTERED:
        return L1Group.l2_cluster_id.is_(None)
    if ref.isdigit():
        return L1Group.l2_cluster_id == int(ref)
    return None


async def _card_thumbnails(db: AsyncSession, scope: object) -> dict[int | None, list[Thumb]]:
    """Representative thumbnails of the largest groups, keyed by L2 cluster id."""
    ranked = (
        select(
            L1Group.l2_cluster_id.label("cluster_id"),
            Image.id,
            Image.filename,
            Image.s3_key,
            Image.s3_thumbnail_key,
            func.row_number()
            .over(partition_by=L1Group.l2_cluster_id, order_by=(L1Group.member_count.desc(), L1Group.id))
            .label("rank"),
        )
        .join(Image, Image.id == L1Group.representative_image_id)
        .where(scope)  # type: ignore[arg-type]
        .subquery()
    )
    rows = await db.execute(select(ranked).where(ranked.c.rank <= THUMBS_PER_CARD).order_by(ranked.c.rank))
    thumbs: dict[int | None, list[Thumb]] = {}
    for row in rows:
        thumbs.setdefault(row.cluster_id, []).append(thumb_for(row.id, row.filename, row.s3_key, row.s3_thumbnail_key))
    return thumbs


async def list_clusters(db: AsyncSession, offset: int, limit: int = CLUSTER_PAGE) -> Page[ClusterCard]:
    total = int(await db.scalar(select(func.count()).select_from(L2Cluster)) or 0)
    clusters = (
        (
            await db.execute(
                select(L2Cluster).order_by(L2Cluster.total_images.desc(), L2Cluster.id).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    thumbs = await _card_thumbnails(db, L1Group.l2_cluster_id.in_([c.id for c in clusters]))
    cards = [
        ClusterCard(
            ref=str(c.id),
            title=c.label or f"Cluster {c.id}",
            total_images=c.total_images,
            group_count=c.member_count,
            thumbnails=thumbs.get(c.id, []),
        )
        for c in clusters
    ]
    return Page(items=cards, total=total, offset=offset, limit=limit)


async def unclustered_card(db: AsyncSession) -> ClusterCard | None:
    scope = L1Group.l2_cluster_id.is_(None)
    group_count, total_images = (
        await db.execute(select(func.count(), func.coalesce(func.sum(L1Group.member_count), 0)).where(scope))
    ).one()
    if not group_count:
        return None
    thumbs = await _card_thumbnails(db, scope)
    return ClusterCard(
        ref=UNCLUSTERED,
        title="Unclustered",
        total_images=int(total_images),
        group_count=int(group_count),
        thumbnails=thumbs.get(None, []),
    )


async def get_cluster_title(db: AsyncSession, ref: str) -> str | None:
    if ref == UNCLUSTERED:
        return "Unclustered"
    if not ref.isdigit():
        return None
    cluster = await db.get(L2Cluster, int(ref))
    if cluster is None:
        return None
    return cluster.label or f"Cluster {cluster.id}"


async def list_groups(db: AsyncSession, ref: str, offset: int, limit: int = GROUP_PAGE) -> Page[GroupRow]:
    scope = _group_scope(ref)
    if scope is None:
        return Page(items=[], total=0, offset=offset, limit=limit)
    total = int(await db.scalar(select(func.count()).select_from(L1Group).where(scope)) or 0)  # type: ignore[arg-type]
    groups = (
        await db.execute(
            select(L1Group.id, L1Group.member_count)
            .where(scope)  # type: ignore[arg-type]
            .order_by(L1Group.member_count.desc(), L1Group.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    group_ids = [g.id for g in groups]

    ranked = (
        select(
            Image.l1_group_id,
            Image.id,
            Image.filename,
            Image.s3_key,
            Image.s3_thumbnail_key,
            func.row_number().over(partition_by=Image.l1_group_id, order_by=(Image.created_at, Image.id)).label("rank"),
        )
        .where(Image.l1_group_id.in_(group_ids))
        .subquery()
    )
    images: dict[int, list[Thumb]] = {}
    for row in await db.execute(select(ranked).where(ranked.c.rank <= THUMBS_PER_GROUP).order_by(ranked.c.rank)):
        images.setdefault(row.l1_group_id, []).append(thumb_for(row.id, row.filename, row.s3_key, row.s3_thumbnail_key))

    product_rows = await db.execute(
        select(Image.l1_group_id, func.min(Image.product_id))
        .where(Image.l1_group_id.in_(group_ids), Image.product_id.isnot(None))
        .group_by(Image.l1_group_id)
    )
    products: dict[int | None, int | None] = {group_id: product_id for group_id, product_id in product_rows.tuples()}
    rows = [
        GroupRow(id=g.id, member_count=g.member_count, product_id=products.get(g.id), images=images.get(g.id, []))
        for g in groups
    ]
    return Page(items=rows, total=total, offset=offset, limit=limit)


async def recent_jobs(db: AsyncSession, limit: int = 20) -> list[Job]:
    return list((await db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit))).scalars())


async def has_active_clustering_job(db: AsyncSession) -> bool:
    """True when a job that takes the pipeline advisory lock is pending or running."""
    count = await db.scalar(
        select(func.count()).select_from(Job).where(Job.type.in_(_CLUSTERING_JOB_TYPES), Job.status.in_(_ACTIVE))
    )
    return bool(count)


def summarize_result(result: str | None) -> str:
    """One-line summary of a job's result JSON: scalar fields only."""
    if not result:
        return ""
    try:
        data = json.loads(result)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    return " · ".join(
        f"{k} {v}" for k, v in data.items() if isinstance(v, int | float | str) and not isinstance(v, bool)
    )


@dataclass(frozen=True)
class StorageInfo:
    label: str
    inbox: str
    hint: str | None = None


def storage_info() -> StorageInfo:
    """Where images live and where new ones go, for display. Never includes credentials."""
    backend = settings.storage_backend
    if backend == "local":
        return StorageInfo(
            label="Local filesystem",
            inbox=f"{str(settings.local_storage_path).rstrip('/')}/images/",
            hint="With Docker Compose, copy files into ./data/images/ next to docker-compose.yml.",
        )
    if backend == "gcs":
        return StorageInfo(label="Google Cloud Storage", inbox=f"gs://{settings.gcs_bucket}/images/")
    host = urlsplit(settings.s3_endpoint_url).hostname if settings.s3_endpoint_url else None
    port = urlsplit(settings.s3_endpoint_url).port if settings.s3_endpoint_url else None
    label = f"S3-compatible at {host}{f':{port}' if port else ''}" if host else "Amazon S3"
    return StorageInfo(label=label, inbox=f"s3://{settings.s3_bucket}/images/")


def gdrive_configured() -> bool:
    return bool(settings.gdrive_folder_id and settings.gdrive_service_account_json)
