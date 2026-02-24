"""add_hnsw_vector_index

Revision ID: c3f8a1b2d4e5
Revises: 002809346eb1
Create Date: 2026-02-11 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f8a1b2d4e5"
down_revision: str | None = "002809346eb1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # HNSW index for cosine similarity search on DINOv2 embeddings (768-dim).
    # Dramatically speeds up k-NN queries from O(n) sequential scan to O(log n).
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_images_embedding_hnsw "
            "ON images USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_images_embedding_hnsw")
