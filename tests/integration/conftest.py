"""Integration test fixtures — real PostgreSQL with pgvector.

Key design: NullPool engine per test avoids asyncpg event-loop binding issues.
Each test gets its own engine + session, with TRUNCATE CASCADE for cleanup.
The client fixture shares the db fixture's session so seeded data is visible.
"""

import logging
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pic.core.database import _build_engine_args
from pic.models.db import Base, Image, Job, JobStatus, JobType, L1Group, L2Cluster


@pytest.fixture
async def db():
    """Per-test async session with NullPool engine (no cross-loop connection reuse)."""
    from pic.config import settings

    db_url, connect_args = _build_engine_args(settings.database_url)
    engine = create_async_engine(db_url, poolclass=NullPool, connect_args=connect_args)

    # Ensure schema exists (idempotent — fast after first test)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        # Cleanup: rollback any pending errors, then truncate all data
        try:
            await session.rollback()
            await session.execute(text("TRUNCATE images, products, l1_groups, l2_clusters, jobs CASCADE"))
            await session.commit()
        except Exception:
            logging.getLogger(__name__).error("Fixture cleanup failed — test data may leak", exc_info=True)
            try:
                await session.rollback()
            except Exception:
                logging.getLogger(__name__).error("Rollback after cleanup failure also failed", exc_info=True)
            raise  # Fail fast — don't let corrupted state leak to next test

    await engine.dispose()


@pytest.fixture
async def db_engine():
    """Standalone NullPool engine for tests that need direct engine access."""
    from pic.config import settings

    db_url, connect_args = _build_engine_args(settings.database_url)
    engine = create_async_engine(db_url, poolclass=NullPool, connect_args=connect_args)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(db):
    """Async HTTP test client sharing the db fixture's session, auth disabled."""

    async def override_get_db():
        yield db  # Reuse the SAME session — seeded data is visible to API

    with patch("pic.core.auth.settings") as mock_auth:
        mock_auth.api_key = ""
        from pic.api.deps import get_db
        from pic.main import app

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
        app.dependency_overrides.clear()


# ─── Factory helpers ───


def make_image_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
async def seed_images(db):
    """Insert a batch of test images and return their IDs."""

    async def _seed(count: int = 3, with_embedding: bool = False, phash: str | None = "aabbccdd11223344") -> list[str]:
        import numpy as np

        ids = []
        for i in range(count):
            img_id = make_image_id()
            embedding = None
            has_emb = 0
            if with_embedding:
                rng = np.random.default_rng(seed=i)
                vec = rng.standard_normal(768).astype(float)
                vec = vec / np.linalg.norm(vec)
                embedding = vec.tolist()
                has_emb = 1

            img = Image(
                id=img_id,
                filename=f"cake_{i}.jpg",
                s3_key=f"processed/cake_{i}.jpg",
                content_hash=f"{img_id[:64]}",
                phash=phash,
                embedding=embedding,
                has_embedding=has_emb,
                width=640,
                height=480,
                file_size=100_000,
            )
            db.add(img)
            ids.append(img_id)
        await db.commit()
        return ids

    return _seed


@pytest.fixture
async def seed_l1_group(db, seed_images):
    """Create an L1 group with member images."""

    async def _seed(member_count: int = 2, with_embedding: bool = False) -> tuple[int, list[str]]:
        image_ids = await seed_images(count=member_count, with_embedding=with_embedding)
        group = L1Group(representative_image_id=image_ids[0], member_count=member_count)
        db.add(group)
        await db.flush()
        for img_id in image_ids:
            img = await db.get(Image, img_id)
            img.l1_group_id = group.id
        await db.commit()
        return group.id, image_ids

    return _seed


@pytest.fixture
async def seed_l2_cluster(db):
    """Create an L2 cluster."""

    async def _seed(label: str = "test-cluster", member_count: int = 1, total_images: int = 3) -> int:
        cluster = L2Cluster(label=label, member_count=member_count, total_images=total_images)
        db.add(cluster)
        await db.commit()
        return cluster.id

    return _seed


@pytest.fixture
async def seed_job(db):
    """Create a job record."""

    async def _seed(
        job_type: JobType = JobType.CLUSTER_FULL,
        status: JobStatus = JobStatus.PENDING,
    ) -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type=job_type, status=status)
        db.add(job)
        await db.commit()
        return job_id

    return _seed
