"""add indexes on representative_image_id columns

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-02-12 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_l1_groups_representative_image_id",
        "l1_groups",
        ["representative_image_id"],
    )
    op.create_index(
        "ix_products_representative_image_id",
        "products",
        ["representative_image_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_representative_image_id", table_name="products")
    op.drop_index("ix_l1_groups_representative_image_id", table_name="l1_groups")
