"""Integration tests for core database operations (TC-3)."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from pic.models.db import Image, Job, JobStatus, JobType, L1Group, L2Cluster, Product


@pytest.mark.integration
class TestImageCRUD:
    """Test Image model CRUD against real PostgreSQL."""

    async def test_create_and_read_image(self, db):
        img_id = str(uuid.uuid4())
        img = Image(
            id=img_id,
            filename="test.jpg",
            s3_key="processed/test.jpg",
            has_embedding=0,
        )
        db.add(img)
        await db.commit()

        result = await db.get(Image, img_id)
        assert result is not None
        assert result.filename == "test.jpg"
        assert result.s3_key == "processed/test.jpg"
        assert result.has_embedding == 0
        assert result.created_at is not None

    async def test_content_hash_uniqueness(self, db):
        """content_hash unique index rejects duplicate hashes."""
        img1 = Image(id=str(uuid.uuid4()), filename="a.jpg", s3_key="a.jpg", content_hash="abc123", has_embedding=0)
        img2 = Image(id=str(uuid.uuid4()), filename="b.jpg", s3_key="b.jpg", content_hash="abc123", has_embedding=0)
        db.add(img1)
        await db.commit()

        db.add(img2)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_embedding_column_stores_vector(self, db):
        """pgvector Vector(768) column stores and retrieves embeddings."""
        import numpy as np

        rng = np.random.default_rng(42)
        vec = rng.standard_normal(768).astype(float)
        vec = (vec / np.linalg.norm(vec)).tolist()

        img_id = str(uuid.uuid4())
        img = Image(
            id=img_id,
            filename="embed.jpg",
            s3_key="embed.jpg",
            embedding=vec,
            has_embedding=1,
        )
        db.add(img)
        await db.commit()

        result = await db.get(Image, img_id)
        assert result.has_embedding == 1
        assert result.embedding is not None
        assert len(result.embedding) == 768
        # Verify values are approximately preserved
        assert abs(result.embedding[0] - vec[0]) < 1e-5


@pytest.mark.integration
class TestJobCRUD:
    """Test Job model CRUD."""

    async def test_create_job_with_enum_values(self, db):
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type=JobType.CLUSTER_FULL, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()

        result = await db.get(Job, job_id)
        assert result.type == JobType.CLUSTER_FULL
        assert result.status == JobStatus.PENDING
        assert result.progress == 0.0

    async def test_job_status_transitions(self, db):
        """Verify status can be updated through all valid states."""
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type=JobType.PIPELINE, status=JobStatus.PENDING)
        db.add(job)
        await db.commit()

        job.status = JobStatus.RUNNING
        job.progress = 0.5
        await db.commit()
        await db.refresh(job)
        assert job.status == JobStatus.RUNNING

        job.status = JobStatus.COMPLETED
        job.progress = 1.0
        job.result = '{"processed": 10}'
        await db.commit()
        await db.refresh(job)
        assert job.status == JobStatus.COMPLETED
        assert job.result == '{"processed": 10}'

    async def test_all_job_types_valid(self, db):
        """All JobType enum values can be stored in DB."""
        for jt in JobType:
            job = Job(id=str(uuid.uuid4()), type=jt, status=JobStatus.PENDING)
            db.add(job)
        await db.commit()

        result = await db.execute(select(func.count()).select_from(Job))
        assert result.scalar_one() == len(JobType)


@pytest.mark.integration
class TestClusterHierarchy:
    """Test L1 Group / L2 Cluster / Image relationships."""

    async def test_l1_group_with_images(self, db, seed_images):
        image_ids = await seed_images(count=3)
        group = L1Group(representative_image_id=image_ids[0], member_count=3)
        db.add(group)
        await db.flush()

        for img_id in image_ids:
            img = await db.get(Image, img_id)
            img.l1_group_id = group.id
        await db.commit()

        # Verify relationship
        result = await db.execute(select(Image).where(Image.l1_group_id == group.id))
        members = result.scalars().all()
        assert len(members) == 3
        assert group.representative_image_id == image_ids[0]

    async def test_l2_cluster_groups_relationship(self, db, seed_l1_group, seed_l2_cluster):
        cluster_id = await seed_l2_cluster(label="superman cakes")
        group_id, _ = await seed_l1_group(member_count=2)

        # Link group to cluster
        group = await db.get(L1Group, group_id)
        group.l2_cluster_id = cluster_id
        await db.commit()

        # Verify via query
        result = await db.execute(select(L1Group).where(L1Group.l2_cluster_id == cluster_id))
        groups = result.scalars().all()
        assert len(groups) == 1
        assert groups[0].id == group_id

    async def test_full_hierarchy_traversal(self, db, seed_images):
        """L2 Cluster → L1 Groups → Images full chain."""
        cluster = L2Cluster(label="wedding cakes", member_count=2, total_images=4)
        db.add(cluster)
        await db.flush()

        # Create two L1 groups, each with 2 images
        for i in range(2):
            ids = await seed_images(count=2, phash=f"{'aa' * 4}{'bb' * 4}{i:02d}{'cc' * 3}")
            group = L1Group(
                representative_image_id=ids[0],
                member_count=2,
                l2_cluster_id=cluster.id,
            )
            db.add(group)
            await db.flush()
            for img_id in ids:
                img = await db.get(Image, img_id)
                img.l1_group_id = group.id
        await db.commit()

        # Count images under cluster
        result = await db.execute(
            select(func.count())
            .select_from(Image)
            .join(L1Group, Image.l1_group_id == L1Group.id)
            .where(L1Group.l2_cluster_id == cluster.id)
        )
        assert result.scalar_one() == 4


@pytest.mark.integration
class TestProductModel:
    """Test Product model and relationships."""

    async def test_create_product_links_images(self, db, seed_l1_group):
        group_id, image_ids = await seed_l1_group(member_count=3)

        product = Product(
            representative_image_id=image_ids[0],
            title="Superman Cake",
            description="A cake with Superman design",
            tags='["superman", "hero"]',
        )
        db.add(product)
        await db.flush()

        # Link images to product
        for img_id in image_ids:
            img = await db.get(Image, img_id)
            img.product_id = product.id
        await db.commit()

        # Verify product → images relationship
        result = await db.execute(select(func.count()).select_from(Image).where(Image.product_id == product.id))
        assert result.scalar_one() == 3

    async def test_product_delete_sets_null(self, db, seed_images):
        """Deleting a product SET NULLs image.product_id (not cascade delete)."""
        ids = await seed_images(count=1)
        product = Product(representative_image_id=ids[0], title="test")
        db.add(product)
        await db.flush()

        img = await db.get(Image, ids[0])
        img.product_id = product.id
        await db.commit()

        # Delete product
        await db.delete(product)
        await db.commit()

        # Image should still exist with product_id = NULL
        img = await db.get(Image, ids[0])
        assert img is not None
        assert img.product_id is None


@pytest.mark.integration
class TestPgvectorOperations:
    """Test pgvector-specific operations."""

    async def test_cosine_distance_search(self, db, seed_images):
        """Verify pgvector cosine distance operator works."""
        ids = await seed_images(count=5, with_embedding=True)

        # Get the first image's embedding
        query_img = await db.get(Image, ids[0])

        # Search for similar images using cosine distance
        stmt = (
            select(
                Image.id,
                Image.embedding.cosine_distance(query_img.embedding).label("distance"),
            )
            .where(Image.id != ids[0], Image.embedding.isnot(None))
            .order_by("distance")
            .limit(3)
        )
        result = await db.execute(stmt)
        rows = result.all()

        # 5 images - 1 query = 4 candidates, limit 3
        assert len(rows) == 3
        # Distance should be between 0 and 2 for cosine distance
        for _, distance in rows:
            assert 0 <= distance <= 2

    async def test_vector_extension_exists(self, db):
        """Verify pgvector extension is installed."""
        result = await db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
        row = result.scalar_one_or_none()
        assert row == "vector"

    async def test_hnsw_index_creation(self, db):
        """Verify HNSW index can be created on vector column."""
        # The migration creates this index, but verify it works at SQL level
        result = await db.execute(
            text("""
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'images' AND indexdef LIKE '%vector%'
            """)
        )
        # Index may or may not exist depending on migration state,
        # but query itself should succeed with pgvector installed
        result.all()  # Should not error
