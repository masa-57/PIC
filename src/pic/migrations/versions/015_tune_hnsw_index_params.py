"""Tune HNSW index parameters for 768-dimensional DINOv2 embeddings.

Default pgvector HNSW params (m=16, ef_construction=64) are suboptimal
for high-dimensional vectors. Increasing m=24 and ef_construction=128
improves recall with acceptable memory tradeoff.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-16 14:02:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_images_embedding_hnsw")
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_images_embedding_hnsw "
            "ON images USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 24, ef_construction = 128)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_images_embedding_hnsw")
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_images_embedding_hnsw ON images USING hnsw (embedding vector_cosine_ops)"
        )
