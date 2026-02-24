"""Phase 2: Add indexes, constraints, and schema improvements.

- Composite index on jobs(status, modal_call_id) for health check polling (#136)
- Index on images(s3_key) for dedup lookups (#152)
- CHECK constraint: has_embedding = 1 ⟺ embedding IS NOT NULL (#138)
- Set hnsw.ef_search session parameter documentation (#153 — runtime only)
- Product.tags TEXT → JSONB (#198)
- L2Cluster viz_x/viz_y CHECK bounds (#199)

Revision ID: 9a1210135365
Revises: d4e5f6a7b8c9a
Create Date: 2026-02-17 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9a1210135365"
down_revision: str | None = "d4e5f6a7b8c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # #136: Composite index on jobs(status, modal_call_id) for health check polling
    op.create_index("ix_jobs_status_modal_call_id", "jobs", ["status", "modal_call_id"])

    # #152: Index on images(s3_key) for pipeline dedup lookups
    op.create_index("ix_images_s3_key", "images", ["s3_key"])

    # #138: CHECK constraint — has_embedding = 1 ⟺ embedding IS NOT NULL
    op.create_check_constraint(
        "ck_images_embedding_consistency",
        "images",
        "(has_embedding = 1) = (embedding IS NOT NULL)",
    )

    # #198: Product.tags TEXT → JSONB
    op.alter_column(
        "products",
        "tags",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="tags::jsonb",
    )

    # #199: CHECK constraints on viz_x/viz_y (bounded to reasonable UMAP range)
    op.create_check_constraint(
        "ck_l2_clusters_viz_x_bounds",
        "l2_clusters",
        "viz_x IS NULL OR (viz_x >= -1000 AND viz_x <= 1000)",
    )
    op.create_check_constraint(
        "ck_l2_clusters_viz_y_bounds",
        "l2_clusters",
        "viz_y IS NULL OR (viz_y >= -1000 AND viz_y <= 1000)",
    )


def downgrade() -> None:
    # Reverse viz bounds constraints
    op.drop_constraint("ck_l2_clusters_viz_y_bounds", "l2_clusters", type_="check")
    op.drop_constraint("ck_l2_clusters_viz_x_bounds", "l2_clusters", type_="check")

    # Reverse Product.tags JSONB → TEXT
    op.alter_column(
        "products",
        "tags",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="tags::text",
    )

    # Reverse CHECK constraint
    op.drop_constraint("ck_images_embedding_consistency", "images", type_="check")

    # Reverse indexes
    op.drop_index("ix_images_s3_key", table_name="images")
    op.drop_index("ix_jobs_status_modal_call_id", table_name="jobs")
