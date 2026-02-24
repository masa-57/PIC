"""Add phash_bits column for SQL-side Hamming distance computation.

Stores the perceptual hash as a PostgreSQL BIT(256) value, enabling
bit_count(phash_bits # query_bits) for database-side duplicate search
instead of loading 1000 images into Python.

Revision ID: d4e5f6a7b8c9a
Revises: c3d4e5f6a7b8
Create Date: 2026-02-16 14:03:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9a"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("images", sa.Column("phash_bits", postgresql.BIT(256), nullable=True))
    # Backfill existing phashes: convert hex string to bit(256)
    # hex_to_bit conversion: each hex char → 4 bits
    op.execute(
        """
        UPDATE images
        SET phash_bits = ('x' || phash)::bit(256)
        WHERE phash IS NOT NULL AND phash_bits IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("images", "phash_bits")
