"""add unique partial index: one product per L1 group

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-11 22:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ix_images_one_product_per_l1 "
        "ON images (l1_group_id) WHERE product_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_images_one_product_per_l1", table_name="images")
