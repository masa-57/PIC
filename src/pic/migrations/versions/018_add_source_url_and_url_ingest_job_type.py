"""Add source_url to images and url_ingest job type.

- Add nullable source_url VARCHAR(2048) to images table
- Add URL_INGEST to jobtype enum

Revision ID: a1b2c3d4e5f6
Revises: 9a1210135365
Create Date: 2026-03-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "9a1210135365"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add source_url column to images table
    op.add_column("images", sa.Column("source_url", sa.String(2048), nullable=True))

    # Add URL_INGEST to jobtype enum
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'url_ingest'")


def downgrade() -> None:
    # Remove source_url column
    op.drop_column("images", "source_url")

    # PostgreSQL does not support removing enum values; no-op for jobtype.
