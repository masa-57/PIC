"""Add missing index on l1_groups.l2_cluster_id.

The ORM model declares index=True but the initial schema migration
never created this index. It is needed for efficient L2 cluster
membership lookups, hierarchy queries, and cascade deletes.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-16 14:01:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_l1_groups_l2_cluster_id", "l1_groups", ["l2_cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_l1_groups_l2_cluster_id", table_name="l1_groups")
