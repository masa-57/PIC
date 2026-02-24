"""Drop invalid unique index that blocked linking all images in an L1 group.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-02-16 12:15:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Previous migration created a unique partial index on images.l1_group_id.
    # That index allows only one image row per L1 group to reference a product,
    # which breaks the expected "link all group images to one product" behavior.
    op.execute("DROP INDEX IF EXISTS ix_images_one_product_per_l1")


def downgrade() -> None:
    op.execute("CREATE UNIQUE INDEX ix_images_one_product_per_l1 ON images (l1_group_id) WHERE product_id IS NOT NULL")
