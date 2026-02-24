from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel, Field, field_validator

from nic.models.db import JobStatus, JobType


class PaginationLinks(BaseModel):
    self_link: str = Field(alias="self")
    next: str | None = None
    prev: str | None = None
    first: str
    last: str | None = None

    model_config = {"populate_by_name": True}


class ClusteringStats(TypedDict):
    total_images: int
    l1_groups: int
    l2_clusters: int
    l2_noise_groups: int


# --- Image ---


class ImageOut(BaseModel):
    id: str
    filename: str
    s3_key: str
    s3_thumbnail_key: str | None = None
    phash: str | None = None
    has_embedding: bool = False
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    l1_group_id: int | None = None
    product_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImageListOut(BaseModel):
    items: list[ImageOut]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


class ImageFileOut(BaseModel):
    presigned_url: str
    expires_in: int = Field(description="Seconds until the presigned URL expires")


# --- L1 Group ---


class L1GroupOut(BaseModel):
    id: int
    representative_image_id: str | None = None
    member_count: int
    l2_cluster_id: int | None = None
    images: list[ImageOut] = []

    model_config = {"from_attributes": True}


class L1GroupBriefOut(BaseModel):
    """L1 group summary without nested images (used in hierarchy views)."""

    id: int
    representative_image_id: str | None = None
    member_count: int
    l2_cluster_id: int | None = None

    model_config = {"from_attributes": True}


class L1GroupListOut(BaseModel):
    items: list[L1GroupBriefOut]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


# --- L2 Cluster ---


class L2ClusterSummary(BaseModel):
    id: int
    label: str | None = None
    member_count: int
    total_images: int
    centroid_image_id: str | None = None
    viz_x: float | None = None
    viz_y: float | None = None

    model_config = {"from_attributes": True}


class L2ClusterOut(BaseModel):
    id: int
    label: str | None = None
    member_count: int
    total_images: int
    centroid_image_id: str | None = None
    viz_x: float | None = None
    viz_y: float | None = None
    groups: list[L1GroupOut] = []

    model_config = {"from_attributes": True}


class L2ClusterHierarchyItemOut(BaseModel):
    """L2 cluster with group summaries (no nested images) for hierarchy view."""

    id: int
    label: str | None = None
    member_count: int
    total_images: int
    centroid_image_id: str | None = None
    viz_x: float | None = None
    viz_y: float | None = None
    groups: list[L1GroupBriefOut] = []

    model_config = {"from_attributes": True}


class L2ClusterListOut(BaseModel):
    items: list[L2ClusterSummary]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


# --- Hierarchy ---


class ClusterHierarchyOut(BaseModel):
    l2_clusters: list[L2ClusterHierarchyItemOut]
    unclustered_groups: list[L1GroupBriefOut]
    total_l2_clusters: int
    total_unclustered_groups: int
    total_l1_groups: int
    total_images: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


# --- Visualization ---


class VisualizationPoint(BaseModel):
    image_id: str
    l1_group_id: int | None = None
    l2_cluster_id: int | None = None
    x: float
    y: float


class VisualizationOut(BaseModel):
    points: list[VisualizationPoint]


# --- Search ---


class SearchResult(BaseModel):
    image_id: str
    filename: str
    s3_key: str
    score: float
    l1_group_id: int | None = None
    l2_cluster_id: int | None = None


class SearchRequest(BaseModel):
    image_id: str
    n_results: int = Field(20, ge=1, le=200)


class DuplicateSearchRequest(BaseModel):
    image_id: str
    threshold: int | None = Field(None, ge=1, le=256)  # Override L1 hash threshold


class SearchResultsOut(BaseModel):
    query_image_id: str
    results: list[SearchResult]


# --- Job ---


class JobOut(BaseModel):
    id: str
    type: JobType
    status: JobStatus
    progress: float
    result: str | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


# --- Clustering Request ---


class ClusterRunRequest(BaseModel):
    l1_min_cluster_size: int | None = Field(None, ge=2, le=100, description="L1 HDBSCAN min cluster size (2-100)")
    l1_min_samples: int | None = Field(None, ge=1, le=50, description="L1 HDBSCAN min samples (1-50)")
    l1_cluster_selection_epsilon: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="L1 HDBSCAN cluster_selection_epsilon — max cosine distance for merging (0.0-1.0)",
    )
    l2_min_cluster_size: int | None = Field(None, ge=2, le=1000, description="Min cluster size for HDBSCAN (2-1000)")
    l2_min_samples: int | None = Field(None, ge=1, le=100, description="Min samples for HDBSCAN core points (1-100)")


# --- Product ---


def _validate_tag_list(v: list[str]) -> list[str]:
    """Shared validation for product tags."""
    if len(v) > 20:
        raise ValueError("Maximum 20 tags allowed")
    cleaned: list[str] = []
    for tag in v:
        tag = tag.strip()
        if not tag:
            raise ValueError("Tags cannot be empty strings")
        if len(tag) > 100:
            raise ValueError(f"Tag too long (max 100 chars): {tag[:20]}...")
        cleaned.append(tag)
    return cleaned


class ProductCreate(BaseModel):
    l1_group_id: int  # Used to find images, NOT stored as FK
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return _validate_tag_list(v)


class ProductUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None  # None = don't update, [] = clear

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_tag_list(v)


class ProductOut(BaseModel):
    id: int
    representative_image_id: str
    title: str | None = None
    description: str | None = None
    tags: list[str] = []
    image_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


class CandidateOut(BaseModel):
    """L1 group without a product — ready for AI processing."""

    l1_group_id: int
    representative_image_id: str | None = None
    representative_url: str
    member_count: int


class CandidateListOut(BaseModel):
    items: list[CandidateOut]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


class ProductImageOut(BaseModel):
    image_id: str
    filename: str
    presigned_url: str
    thumbnail_url: str | None = None
    is_representative: bool
    width: int | None = None
    height: int | None = None


class ProductImageListOut(BaseModel):
    items: list[ProductImageOut]
    total: int
    offset: int = 0
    limit: int = 50
    links: PaginationLinks | None = None


# --- Error ---


class ErrorDetail(BaseModel):
    detail: str
    request_id: str | None = None


class ProblemDetail(BaseModel):
    """RFC 7807 problem detail response."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None


# --- Health ---


class HealthOut(BaseModel):
    status: str
    database: str


class PoolStatusOut(BaseModel):
    pool_size: int = 0
    checked_out: int = 0
    checked_in: int = 0
    overflow: int = 0


class DetailedHealthOut(BaseModel):
    status: str
    database: str
    recent_failed_jobs: int = 0
    stale_jobs_swept: int = 0
    connection_pool: PoolStatusOut | None = None
