"""Add GDRIVE_SYNC to jobtype enum.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-02-13 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'GDRIVE_SYNC'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op.
    pass
