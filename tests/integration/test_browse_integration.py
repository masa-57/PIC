"""Integration tests for UI read models against real PostgreSQL (#113)."""

import pytest

from pic.models.db import JobStatus, JobType, L1Group
from pic.services import browse


@pytest.fixture(autouse=True)
def local_storage(monkeypatch):
    """Thumbnail URLs must not need S3 credentials in tests."""
    monkeypatch.setattr(browse.settings, "storage_backend", "local")


@pytest.mark.integration
class TestClusters:
    async def test_lists_clusters_with_representative_thumbnails(self, db, seed_l1_group, seed_l2_cluster):
        cluster_id = await seed_l2_cluster(label="mugs", member_count=1, total_images=2)
        group_id, image_ids = await seed_l1_group(member_count=2)
        group = await db.get(L1Group, group_id)
        group.l2_cluster_id = cluster_id
        await db.commit()

        page = await browse.list_clusters(db, offset=0)

        assert page.total == 1
        card = page.items[0]
        assert (card.ref, card.title, card.total_images, card.group_count) == (str(cluster_id), "mugs", 2, 1)
        assert [t.id for t in card.thumbnails] == [image_ids[0]]

    async def test_unclustered_card_covers_groups_without_l2(self, db, seed_l1_group):
        await seed_l1_group(member_count=3)
        card = await browse.unclustered_card(db)
        assert card is not None
        assert (card.ref, card.total_images, card.group_count) == ("unclustered", 3, 1)

    async def test_unclustered_card_is_none_when_empty(self, db):
        assert await browse.unclustered_card(db) is None


@pytest.mark.integration
class TestGroups:
    async def test_caps_thumbnails_per_group(self, db, seed_l1_group):
        group_id, _ = await seed_l1_group(member_count=15)
        page = await browse.list_groups(db, "unclustered", offset=0)
        row = page.items[0]
        assert row.id == group_id
        assert len(row.images) == browse.THUMBS_PER_GROUP
        assert row.more == 3

    async def test_reports_product_of_group(self, db, seed_l1_group):
        from pic.services import curation

        group_id, _ = await seed_l1_group(member_count=2)
        created = await curation.create_product(db, l1_group_ids=[group_id])
        page = await browse.list_groups(db, "unclustered", offset=0)
        assert page.items[0].product_id == created.product_id

    async def test_unknown_cluster_title_is_none(self, db):
        assert await browse.get_cluster_title(db, "999999") is None
        assert await browse.get_cluster_title(db, "not-a-number") is None
        assert await browse.get_cluster_title(db, "unclustered") == "Unclustered"


@pytest.mark.integration
class TestJobs:
    async def test_active_clustering_job_detection(self, db, seed_job):
        assert await browse.has_active_clustering_job(db) is False
        await seed_job(job_type=JobType.URL_INGEST, status=JobStatus.RUNNING)
        assert await browse.has_active_clustering_job(db) is False
        await seed_job(job_type=JobType.PIPELINE, status=JobStatus.PENDING)
        assert await browse.has_active_clustering_job(db) is True

    async def test_recent_jobs_newest_first(self, db, seed_job):
        first = await seed_job()
        second = await seed_job()
        jobs = await browse.recent_jobs(db)
        assert {j.id for j in jobs} == {first, second}


@pytest.mark.integration
class TestTypicalDurations:
    async def test_median_of_recent_completed_jobs_per_type(self, db):
        import uuid
        from datetime import UTC, datetime, timedelta

        from pic.models.db import Job

        base = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
        for i, seconds in enumerate([10, 30, 20]):
            created = base + timedelta(minutes=i)
            db.add(
                Job(
                    id=str(uuid.uuid4()),
                    type=JobType.CLUSTER_FULL,
                    status=JobStatus.COMPLETED,
                    created_at=created,
                    completed_at=created + timedelta(seconds=seconds),
                )
            )
        db.add(
            Job(
                id=str(uuid.uuid4()), type=JobType.PIPELINE, status=JobStatus.FAILED, created_at=base, completed_at=base
            )
        )
        await db.commit()

        durations = await browse.typical_durations(db)

        assert durations == {JobType.CLUSTER_FULL: 20.0}


@pytest.mark.integration
class TestProductChoices:
    async def test_lists_products_newest_first_with_fallback_title(self, db, seed_l1_group):
        from pic.services import curation

        g1, _ = await seed_l1_group(member_count=1)
        g2, _ = await seed_l1_group(member_count=1)
        first = await curation.create_product(db, l1_group_ids=[g1], title="Mug")
        second = await curation.create_product(db, l1_group_ids=[g2])

        choices = await browse.list_product_choices(db)

        assert choices == [(second.product_id, f"Product #{second.product_id}"), (first.product_id, "Mug")]
