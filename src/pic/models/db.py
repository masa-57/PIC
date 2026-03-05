import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pic.models.types import AsyncpgBIT


class Base(DeclarativeBase):
    pass


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(enum.StrEnum):
    INGEST = "ingest"
    CLUSTER_L1 = "cluster_l1"
    CLUSTER_L2 = "cluster_l2"
    CLUSTER_FULL = "cluster_full"
    PIPELINE = "pipeline"
    GDRIVE_SYNC = "gdrive_sync"
    URL_INGEST = "url_ingest"


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        Index("ix_images_s3_key", "s3_key"),
        CheckConstraint("(has_embedding = 1) = (embedding IS NOT NULL)", name="ck_images_embedding_consistency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    s3_thumbnail_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, unique=True, nullable=True)
    phash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    phash_bits = mapped_column(AsyncpgBIT(256), nullable=True)  # Binary phash for SQL-side Hamming
    dhash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding = mapped_column(Vector(768), nullable=True)  # DINOv2 base: 768-dim
    has_embedding: Mapped[bool] = mapped_column(Integer, index=True, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    l1_group_id: Mapped[int | None] = mapped_column(ForeignKey("l1_groups.id"), index=True, nullable=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    l1_group: Mapped["L1Group | None"] = relationship(back_populates="images", foreign_keys=[l1_group_id])
    product: Mapped["Product | None"] = relationship(back_populates="images", foreign_keys=[product_id])


class L1Group(Base):
    """Near-duplicate group (Level 1)."""

    __tablename__ = "l1_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    representative_image_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("images.id"), index=True, nullable=True
    )
    member_count: Mapped[int] = mapped_column(Integer, default=1)
    l2_cluster_id: Mapped[int | None] = mapped_column(ForeignKey("l2_clusters.id"), index=True, nullable=True)

    images: Mapped[list["Image"]] = relationship(back_populates="l1_group", foreign_keys="[Image.l1_group_id]")
    l2_cluster: Mapped["L2Cluster | None"] = relationship(back_populates="groups")


class L2Cluster(Base):
    """Semantic cluster (Level 2)."""

    __tablename__ = "l2_clusters"
    __table_args__ = (
        CheckConstraint("viz_x IS NULL OR (viz_x >= -1000 AND viz_x <= 1000)", name="ck_l2_clusters_viz_x_bounds"),
        CheckConstraint("viz_y IS NULL OR (viz_y >= -1000 AND viz_y <= 1000)", name="ck_l2_clusters_viz_y_bounds"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    total_images: Mapped[int] = mapped_column(Integer, default=0)
    centroid_image_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    viz_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    viz_y: Mapped[float | None] = mapped_column(Float, nullable=True)

    groups: Mapped[list["L1Group"]] = relationship(back_populates="l2_cluster")


class Product(Base):
    """AI-enriched product derived from an L1 near-duplicate group."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    representative_image_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("images.id"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags = mapped_column(JSONB, nullable=True)  # JSON array stored as native JSONB
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    images: Mapped[list["Image"]] = relationship(back_populates="product", foreign_keys="[Image.product_id]")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_modal_call_id", "status", "modal_call_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), index=True, default=JobStatus.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    modal_call_id: Mapped[str | None] = mapped_column(String(256), nullable=True)  # Modal function call ID
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
