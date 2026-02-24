"""initial schema

Revision ID: aa8f7a7ee565
Revises:
Create Date: 2026-02-09 13:24:33.441509

"""
from typing import Sequence, Union

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa8f7a7ee565'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tables without circular FKs first
    op.create_table('l2_clusters',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('label', sa.String(length=256), nullable=True),
    sa.Column('member_count', sa.Integer(), nullable=False),
    sa.Column('total_images', sa.Integer(), nullable=False),
    sa.Column('centroid_image_id', sa.String(length=36), nullable=True),
    sa.Column('viz_x', sa.Float(), nullable=True),
    sa.Column('viz_y', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('l1_groups',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('representative_image_id', sa.String(length=36), nullable=True),
    sa.Column('member_count', sa.Integer(), nullable=False),
    sa.Column('l2_cluster_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['l2_cluster_id'], ['l2_clusters.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('images',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('s3_key', sa.String(length=1024), nullable=False),
    sa.Column('s3_thumbnail_key', sa.String(length=1024), nullable=True),
    sa.Column('phash', sa.String(length=64), nullable=True),
    sa.Column('dhash', sa.String(length=64), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('has_embedding', sa.Integer(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('file_size', sa.Integer(), nullable=True),
    sa.Column('l1_group_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['l1_group_id'], ['l1_groups.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_images_phash'), 'images', ['phash'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.Enum('INGEST', 'CLUSTER_L1', 'CLUSTER_L2', 'CLUSTER_FULL', name='jobtype'), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', name='jobstatus'), nullable=False),
    sa.Column('progress', sa.Float(), nullable=False),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # Add deferred FK from l1_groups back to images (circular reference)
    op.create_foreign_key('fk_l1_representative_image', 'l1_groups', 'images',
                          ['representative_image_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_l1_representative_image', 'l1_groups', type_='foreignkey')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_images_phash'), table_name='images')
    op.drop_table('images')
    op.drop_table('l1_groups')
    op.drop_table('l2_clusters')
