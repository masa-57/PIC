"""Add params JSONB column to jobs.

The local worker reads job input from this column; Modal still receives it as a
function argument.

Revision ID: 7b3e9c2a4f10
Revises: 06d7586a44c8
Create Date: 2026-09-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "7b3e9c2a4f10"
down_revision: str | None = "06d7586a44c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("params", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "params")
