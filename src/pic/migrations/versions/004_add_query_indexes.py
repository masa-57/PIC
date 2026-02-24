"""add indexes for l1_group_id and job status

Revision ID: d4e5f6a7b8c9
Revises: c3f8a1b2d4e5
Create Date: 2026-02-11 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3f8a1b2d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_images_l1_group_id", "images", ["l1_group_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_images_l1_group_id", table_name="images")
