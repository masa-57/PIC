"""fix pipeline jobtype enum case

The original migration 002809346eb1 added 'pipeline' (lowercase) to the
jobtype enum, but SQLAlchemy's Enum(JobType) sends the Python enum .name
('PIPELINE', uppercase). The existing DB enum values are all uppercase
(INGEST, CLUSTER_L1, etc.), so this migration adds the uppercase variant
to match the convention.

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-02-12 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'PIPELINE'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op.
    pass
