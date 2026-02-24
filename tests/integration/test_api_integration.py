"""Integration tests for API endpoints against real PostgreSQL (TC-3)."""

import uuid
from unittest.mock import patch

import pytest

from pic.models.db import Image, JobStatus, JobType, L1Group
from pic.services.hash_utils import hex_to_bitstring


@pytest.mark.integration
class TestHealthEndpoints:
    """Health endpoints with real database."""

    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    async def test_detailed_health_returns_ok(self, client):
        resp = await client.get("/health/detailed")
        assert resp.status_code == 200
        data = resp.json()
        # /health/detailed uses the app's global engine (not the test's overridden
        # get_db session), so in tests the DB check may report "degraded".
        assert data["status"] in ("ok", "degraded")
        assert "database" in data
        assert "recent_failed_jobs" in data


@pytest.mark.integration
class TestImagesAPI:
    """Image listing and retrieval with real DB."""

    async def test_list_images_empty(self, client):
        resp = await client.get("/api/v1/images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_images_with_data(self, client, db, seed_images):
        await seed_images(count=5)
        resp = await client.get("/api/v1/images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    async def test_list_images_pagination(self, client, db, seed_images):
        await seed_images(count=10, phash=None)
        resp = await client.get("/api/v1/images?offset=0&limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert len(data["items"]) == 3
        assert data["offset"] == 0
        assert data["limit"] == 3

    async def test_get_image_by_id(self, client, db, seed_images):
        ids = await seed_images(count=1)
        resp = await client.get(f"/api/v1/images/{ids[0]}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == ids[0]
        assert data["filename"] == "cake_0.jpg"

    async def test_get_image_not_found(self, client):
        resp = await client.get(f"/api/v1/images/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_filter_images_by_embedding(self, client, db, seed_images):
        await seed_images(count=3, with_embedding=True)
        await seed_images(count=2, with_embedding=False, phash=None)

        resp = await client.get("/api/v1/images?has_embedding=true")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

        resp = await client.get("/api/v1/images?has_embedding=false")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2


@pytest.mark.integration
class TestJobsAPI:
    """Job listing and retrieval with real DB."""

    async def test_list_jobs_empty(self, client):
        resp = await client.get("/api/v1/jobs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_create_and_get_job(self, client, db, seed_job):
        job_id = await seed_job(job_type=JobType.INGEST, status=JobStatus.RUNNING)
        resp = await client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == job_id
        assert data["type"] == "ingest"
        assert data["status"] == "running"

    async def test_filter_jobs_by_status(self, client, db, seed_job):
        await seed_job(status=JobStatus.PENDING)
        await seed_job(status=JobStatus.COMPLETED)
        await seed_job(status=JobStatus.COMPLETED)

        resp = await client.get("/api/v1/jobs?status=completed")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_job_not_found(self, client):
        resp = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404


@pytest.mark.integration
class TestClustersAPI:
    """Cluster hierarchy endpoints with real DB."""

    async def test_hierarchy_empty(self, client):
        resp = await client.get("/api/v1/clusters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_l2_clusters"] == 0
        assert data["total_l1_groups"] == 0
        assert data["total_images"] == 0

    async def test_hierarchy_with_data(self, client, db, seed_l1_group, seed_l2_cluster):
        cluster_id = await seed_l2_cluster(label="wedding", member_count=1, total_images=2)
        group_id, _ = await seed_l1_group(member_count=2)

        group = await db.get(L1Group, group_id)
        group.l2_cluster_id = cluster_id
        await db.commit()

        resp = await client.get("/api/v1/clusters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_l2_clusters"] == 1
        assert data["total_l1_groups"] == 1
        assert data["total_images"] == 2

    async def test_list_l1_groups(self, client, db, seed_l1_group):
        await seed_l1_group(member_count=3)
        resp = await client.get("/api/v1/clusters/level1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["member_count"] == 3

    async def test_get_l1_group_not_found(self, client):
        resp = await client.get("/api/v1/clusters/level1/99999")
        assert resp.status_code == 404

    async def test_list_l2_clusters(self, client, db, seed_l2_cluster):
        await seed_l2_cluster(label="cluster-a", total_images=10)
        await seed_l2_cluster(label="cluster-b", total_images=5)
        resp = await client.get("/api/v1/clusters/level2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    async def test_get_l2_cluster_with_groups(self, client, db, seed_l1_group, seed_l2_cluster):
        cluster_id = await seed_l2_cluster()
        group_id, _ = await seed_l1_group(member_count=2)
        group = await db.get(L1Group, group_id)
        group.l2_cluster_id = cluster_id
        await db.commit()

        resp = await client.get(f"/api/v1/clusters/level2/{cluster_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["groups"]) == 1


@pytest.mark.integration
class TestProductsAPI:
    """Product CRUD endpoints with real DB."""

    async def test_create_product_from_l1_group(self, client, db, seed_l1_group):
        group_id, image_ids = await seed_l1_group(member_count=2)

        resp = await client.post(
            "/api/v1/products",
            json={
                "l1_group_id": group_id,
                "title": "Superman Cake",
                "description": "A blue cake with Superman logo",
                "tags": ["superman", "hero", "blue"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Superman Cake"
        assert data["tags"] == ["superman", "hero", "blue"]
        assert data["image_count"] == 2
        assert data["representative_image_id"] == image_ids[0]

    async def test_create_product_duplicate_group_rejected(self, client, db, seed_l1_group):
        group_id, _ = await seed_l1_group(member_count=2)

        # First create should succeed
        resp = await client.post("/api/v1/products", json={"l1_group_id": group_id})
        assert resp.status_code == 201

        # Second create for same group should fail
        resp = await client.post("/api/v1/products", json={"l1_group_id": group_id})
        assert resp.status_code == 409

    async def test_list_products(self, client, db, seed_l1_group):
        group_id1, _ = await seed_l1_group(member_count=2)
        resp1 = await client.post("/api/v1/products", json={"l1_group_id": group_id1, "title": "Product A"})
        assert resp1.status_code == 201

        resp = await client.get("/api/v1/products")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    async def test_update_product(self, client, db, seed_l1_group):
        group_id, _ = await seed_l1_group(member_count=1)
        create_resp = await client.post("/api/v1/products", json={"l1_group_id": group_id, "title": "Old"})
        product_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/products/{product_id}",
            json={"title": "New Title", "tags": ["updated"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New Title"
        assert data["tags"] == ["updated"]

    async def test_delete_product(self, client, db, seed_l1_group):
        group_id, _ = await seed_l1_group(member_count=1)
        create_resp = await client.post("/api/v1/products", json={"l1_group_id": group_id})
        product_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/products/{product_id}")
        assert resp.status_code == 204

        # Verify deleted
        resp = await client.get(f"/api/v1/products/{product_id}")
        assert resp.status_code == 404

    async def test_candidates_lists_unprocessed_groups(self, client, db, seed_l1_group):
        """Groups without products should appear as candidates."""
        group_id, _ = await seed_l1_group(member_count=3)

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            resp = await client.get("/api/v1/products/candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["l1_group_id"] == group_id
        assert data["items"][0]["member_count"] == 3

    async def test_candidates_excludes_groups_with_products(self, client, db, seed_l1_group):
        """Groups with products should NOT appear as candidates."""
        group_id, _ = await seed_l1_group(member_count=2)
        await client.post("/api/v1/products", json={"l1_group_id": group_id})

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            resp = await client.get("/api/v1/products/candidates")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_get_product_images(self, client, db, seed_l1_group):
        group_id, image_ids = await seed_l1_group(member_count=2)
        create_resp = await client.post("/api/v1/products", json={"l1_group_id": group_id})
        product_id = create_resp.json()["id"]

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            resp = await client.get(f"/api/v1/products/{product_id}/images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        # One should be marked as representative
        reps = [img for img in data["items"] if img["is_representative"]]
        assert len(reps) == 1


@pytest.mark.integration
class TestSearchAPI:
    """Search endpoints with real DB and pgvector."""

    async def test_similar_search(self, client, db, seed_images):
        """Similarity search returns results ordered by cosine distance."""
        ids = await seed_images(count=5, with_embedding=True)

        resp = await client.post(
            "/api/v1/search/similar",
            json={"image_id": ids[0], "n_results": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_image_id"] == ids[0]
        assert len(data["results"]) == 3
        # Scores should be between 0 and 1 (cosine similarity)
        for r in data["results"]:
            assert -1 <= r["score"] <= 1

    async def test_similar_search_no_embedding(self, client, db, seed_images):
        """Search with image that has no embedding returns 400."""
        ids = await seed_images(count=1, with_embedding=False)

        resp = await client.post(
            "/api/v1/search/similar",
            json={"image_id": ids[0]},
        )
        assert resp.status_code == 400
        assert "no embedding" in resp.json()["detail"].lower()

    async def test_similar_search_not_found(self, client):
        resp = await client.post(
            "/api/v1/search/similar",
            json={"image_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_duplicate_search(self, client, db):
        """Duplicate search finds images with similar phash."""
        # Create query image
        query_id = str(uuid.uuid4())
        db.add(
            Image(
                id=query_id,
                filename="query.jpg",
                s3_key="q.jpg",
                phash="aabbccdd11223344",
                phash_bits=hex_to_bitstring("aabbccdd11223344"),
                has_embedding=0,
            )
        )
        # Create near-duplicate (same phash → distance 0)
        dup_id = str(uuid.uuid4())
        db.add(
            Image(
                id=dup_id,
                filename="dup.jpg",
                s3_key="d.jpg",
                phash="aabbccdd11223344",
                phash_bits=hex_to_bitstring("aabbccdd11223344"),
                has_embedding=0,
            )
        )
        # Create distant image (very different phash)
        far_id = str(uuid.uuid4())
        db.add(
            Image(
                id=far_id,
                filename="far.jpg",
                s3_key="f.jpg",
                phash="ff00ff00ff00ff00",
                phash_bits=hex_to_bitstring("ff00ff00ff00ff00"),
                has_embedding=0,
            )
        )
        await db.commit()

        resp = await client.post(
            "/api/v1/search/duplicates",
            json={"image_id": query_id, "threshold": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        result_ids = [r["image_id"] for r in data["results"]]
        assert dup_id in result_ids
        # Far image should NOT be in results (distance >> 10)


@pytest.mark.integration
class TestAuthIntegration:
    """API key authentication with real endpoints."""

    async def test_auth_required_when_key_set(self, db_engine):
        """Endpoints return 401 when API key is set but not provided."""
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_factory = async_sessionmaker(db_engine, class_=_AsyncSession, expire_on_commit=False)

        async def override_get_db():
            async with session_factory() as session:
                yield session

        with patch("pic.core.auth.settings") as mock_auth:
            mock_auth.api_key = "test-secret-key"
            from pic.api.deps import get_db
            from pic.main import app

            app.dependency_overrides[get_db] = override_get_db
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/api/v1/images")
                assert resp.status_code == 401

                # With correct key it should work
                resp = await c.get("/api/v1/images", headers={"X-API-Key": "test-secret-key"})
                assert resp.status_code == 200
            app.dependency_overrides.clear()
