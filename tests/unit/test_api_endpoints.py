"""Unit tests for API endpoints using httpx AsyncClient."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_image(**overrides):
    """Create a mock Image ORM object."""
    img = MagicMock()
    img.id = overrides.get("id", "img-1")
    img.filename = overrides.get("filename", "photo.jpg")
    img.s3_key = overrides.get("s3_key", "processed/photo.jpg")
    img.s3_thumbnail_key = overrides.get("s3_thumbnail_key")
    img.phash = overrides.get("phash", "f0e1d2c3b4a59687")
    img.has_embedding = overrides.get("has_embedding", 1)
    img.width = overrides.get("width", 800)
    img.height = overrides.get("height", 600)
    img.file_size = overrides.get("file_size", 102400)
    img.l1_group_id = overrides.get("l1_group_id")
    img.source_url = overrides.get("source_url")
    img.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    return img


def _make_job(**overrides):
    """Create a mock Job ORM object."""
    from pic.models.db import JobStatus, JobType

    job = MagicMock()
    job.id = overrides.get("id", "job-1")
    job.type = overrides.get("type", JobType.CLUSTER_FULL)
    job.status = overrides.get("status", JobStatus.COMPLETED)
    job.progress = overrides.get("progress", 1.0)
    job.result = overrides.get("result")
    job.error = overrides.get("error")
    job.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    job.completed_at = overrides.get("completed_at")
    return job


def _make_l1_group(**overrides):
    """Create a mock L1Group ORM object."""
    group = MagicMock()
    group.id = overrides.get("id", 1)
    group.representative_image_id = overrides.get("representative_image_id", "img-1")
    group.member_count = overrides.get("member_count", 3)
    group.l2_cluster_id = overrides.get("l2_cluster_id")
    group.images = overrides.get("images", [])
    return group


def _make_product(**overrides):
    """Create a mock Product ORM object."""
    product = MagicMock()
    product.id = overrides.get("id", 1)
    product.representative_image_id = overrides.get("representative_image_id", "img-1")
    product.title = overrides.get("title", "Blue Widget")
    product.description = overrides.get("description", "A blue and red widget product")
    product.tags = overrides.get("tags", ["blue", "widget"])
    product.created_at = overrides.get("created_at", datetime(2026, 1, 1))
    product.updated_at = overrides.get("updated_at")
    product.images = overrides.get(
        "images", [_make_image(id="img-1", product_id=1), _make_image(id="img-2", product_id=1)]
    )
    return product


@pytest.fixture
def client():
    """Create a test client with mocked DB dependency and auth disabled."""
    with patch("pic.core.auth.settings") as mock_auth_settings:
        mock_auth_settings.api_key = ""  # Disable auth for most tests
        from pic.main import app

        with TestClient(app) as c:
            yield c


@pytest.fixture
def mock_db():
    """Create a mock async DB session."""
    return AsyncMock()


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    """Guarantee dependency overrides are cleared even when a test errors."""
    yield
    from pic.main import app

    app.dependency_overrides.clear()


@pytest.fixture
def override_db(mock_db):
    """Override get_db dependency with mock session; auto-clears after test."""
    from pic.api.deps import get_db
    from pic.main import app

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db
    yield mock_db
    app.dependency_overrides.clear()


@pytest.mark.unit
class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        with patch("pic.main.engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] in ("ok", "degraded")

    def test_health_does_not_leak_errors(self, client):
        """Health check should not expose internal error details."""
        with patch("pic.main.engine") as mock_engine:
            mock_engine.connect.side_effect = Exception("connection refused postgresql://user:secret@host:5432/db")
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            # Should NOT contain the connection string
            assert "secret" not in data["database"]
            assert "postgresql" not in data["database"]
            assert data["database"] == "error"


@pytest.mark.unit
class TestImagesEndpoint:
    def test_list_images(self, client, override_db):
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "img-1"

    def test_get_image_not_found(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/images/nonexistent")
        assert response.status_code == 404
        payload = response.json()
        assert "request_id" in payload
        assert payload["detail"] == "Image not found"

    def test_get_image_found(self, client, override_db):
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/images/img-1")
        assert response.status_code == 200
        assert response.json()["id"] == "img-1"

    def test_list_images_offset_too_large_rejected(self, client, override_db):
        response = client.get("/api/v1/images?offset=10001")
        assert response.status_code == 422

    def test_get_image_file_thumbnail_true_uses_thumbnail_key(self, client, override_db):
        img = _make_image(id="img-1", s3_key="processed/photo.jpg", s3_thumbnail_key="thumbnails/photo.jpg")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        with patch("pic.api.images.generate_presigned_url", return_value="https://example.com/thumb") as mock_presign:
            response = client.get("/api/v1/images/img-1/file?thumbnail=true")

        assert response.status_code == 200
        assert response.json()["presigned_url"] == "https://example.com/thumb"
        mock_presign.assert_called_once_with("thumbnails/photo.jpg")

    def test_get_image_file_thumbnail_true_falls_back_when_thumbnail_missing(self, client, override_db):
        img = _make_image(id="img-1", s3_key="processed/photo.jpg", s3_thumbnail_key=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "pic.api.images.generate_presigned_url", return_value="https://example.com/original"
        ) as mock_presign:
            response = client.get("/api/v1/images/img-1/file?thumbnail=true")

        assert response.status_code == 200
        assert response.json()["presigned_url"] == "https://example.com/original"
        mock_presign.assert_called_once_with("processed/photo.jpg")

    def test_list_images_filters_by_l1_group_id(self, client, override_db):
        img = _make_image(id="img-1", l1_group_id=42)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images?l1_group_id=42")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["l1_group_id"] == 42

        list_stmt = override_db.execute.call_args_list[0].args[0]
        count_stmt = override_db.execute.call_args_list[1].args[0]
        assert "images.l1_group_id" in str(list_stmt)
        assert "images.l1_group_id" in str(count_stmt)
        assert 42 in list_stmt.compile().params.values()
        assert 42 in count_stmt.compile().params.values()


@pytest.mark.unit
class TestJobsEndpoint:
    def test_list_jobs(self, client, override_db):
        job = _make_job()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [job]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_get_job_not_found(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/jobs/nonexistent")
        assert response.status_code == 404


@pytest.mark.unit
class TestAuthGlobal:
    """Test that all API routes require auth when api_key is configured."""

    def test_images_requires_auth(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            with TestClient(app) as c:
                response = c.get("/api/v1/images")
                assert response.status_code == 401

    def test_clusters_requires_auth(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            with TestClient(app) as c:
                response = c.get("/api/v1/clusters")
                assert response.status_code == 401

    def test_jobs_requires_auth(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            with TestClient(app) as c:
                response = c.get("/api/v1/jobs")
                assert response.status_code == 401

    def test_search_requires_auth(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            with TestClient(app) as c:
                response = c.post("/api/v1/search/similar", json={"image_id": "x"})
                assert response.status_code == 401

    def test_valid_key_passes(self, mock_db):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_count = MagicMock()
            mock_count.scalar_one.return_value = 0
            mock_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

            from pic.api.deps import get_db

            async def _mock_get_db():
                yield mock_db

            app.dependency_overrides[get_db] = _mock_get_db

            try:
                with TestClient(app) as c:
                    response = c.get("/api/v1/images", headers={"X-API-Key": "secret-key"})
                    assert response.status_code == 200
            finally:
                app.dependency_overrides.clear()


@pytest.mark.unit
class TestInputValidation:
    """Test that input bounds are enforced on request schemas."""

    def test_search_n_results_too_high(self, client, override_db):
        response = client.post(
            "/api/v1/search/similar",
            json={"image_id": "img-1", "n_results": 999},
        )
        assert response.status_code == 422

    def test_search_n_results_zero(self, client, override_db):
        response = client.post(
            "/api/v1/search/similar",
            json={"image_id": "img-1", "n_results": 0},
        )
        assert response.status_code == 422

    def test_cluster_epsilon_negative(self, client, override_db):
        response = client.post(
            "/api/v1/clusters/run",
            json={"l1_cluster_selection_epsilon": -0.5},
        )
        assert response.status_code == 422

    def test_cluster_epsilon_too_high(self, client, override_db):
        response = client.post(
            "/api/v1/clusters/run",
            json={"l1_cluster_selection_epsilon": 1.5},
        )
        assert response.status_code == 422

    def test_cluster_l2_min_samples_too_high(self, client, override_db):
        response = client.post(
            "/api/v1/clusters/run",
            json={"l2_min_samples": 101},
        )
        assert response.status_code == 422


@pytest.mark.unit
class TestOpenApiSpec:
    def test_error_schema_uses_problem_detail(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200

        schema_ref = response.json()["paths"]["/api/v1/images/{image_id}"]["get"]["responses"]["404"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        assert schema_ref.endswith("/ProblemDetail")


@pytest.mark.unit
class TestClustersEndpoint:
    def test_run_clustering_returns_202(self, client, override_db):
        from pic.models.db import JobStatus, JobType

        job = _make_job(type=JobType.CLUSTER_FULL, status=JobStatus.PENDING)
        mock_pending_result = MagicMock()
        mock_pending_result.scalar_one.return_value = 0
        override_db.execute = AsyncMock(return_value=mock_pending_result)
        override_db.add = MagicMock()
        override_db.commit = AsyncMock()

        # Mock refresh to set job attributes that will be validated
        async def mock_refresh(obj):
            obj.id = job.id
            obj.type = job.type
            obj.status = job.status
            obj.progress = 0.0
            obj.result = None
            obj.error = None
            obj.created_at = job.created_at
            obj.completed_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch("pic.api.clusters.submit_cluster_job", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = None
            response = client.post("/api/v1/clusters/run", json={})
            assert response.status_code == 202
            assert override_db.add.called
            assert override_db.commit.called

    def test_run_clustering_returns_location_header(self, client, override_db):
        """202 response should include Location header pointing to job."""
        from pic.models.db import JobStatus, JobType

        job = _make_job(id="job-abc", type=JobType.CLUSTER_FULL, status=JobStatus.PENDING)
        mock_pending_result = MagicMock()
        mock_pending_result.scalar_one.return_value = 0
        override_db.execute = AsyncMock(return_value=mock_pending_result)
        override_db.add = MagicMock()
        override_db.commit = AsyncMock()

        async def mock_refresh(obj):
            obj.id = "job-abc"
            obj.type = job.type
            obj.status = job.status
            obj.progress = 0.0
            obj.result = None
            obj.error = None
            obj.created_at = job.created_at
            obj.completed_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch("pic.api.clusters.submit_cluster_job", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = None
            response = client.post("/api/v1/clusters/run", json={})
            assert response.status_code == 202
            assert response.headers.get("location") == "/api/v1/jobs/job-abc"

    def test_run_clustering_modal_failure_returns_503(self, client, override_db):
        mock_pending_result = MagicMock()
        mock_pending_result.scalar_one.return_value = 0
        override_db.add = MagicMock()
        override_db.commit = AsyncMock()

        async def mock_refresh(obj):
            pass

        override_db.refresh = AsyncMock(side_effect=mock_refresh)
        override_db.execute = AsyncMock(side_effect=[mock_pending_result, MagicMock()])

        with patch("pic.api.clusters.submit_cluster_job", new_callable=AsyncMock) as mock_submit:
            mock_submit.side_effect = Exception("Modal service unavailable")
            response = client.post("/api/v1/clusters/run", json={})
            assert response.status_code == 503

    def test_get_hierarchy(self, client, override_db):
        # Mock result for L2 clusters query (paginated)
        mock_l2_result = MagicMock()
        mock_l2_result.scalars.return_value.all.return_value = []

        # Mock result for total L2 clusters count
        mock_l2_count = MagicMock()
        mock_l2_count.scalar_one.return_value = 0

        # Mock result for unclustered L1 groups query (paginated)
        mock_l1_result = MagicMock()
        mock_l1_result.scalars.return_value.all.return_value = []

        # Mock result for total unclustered groups count
        mock_unclustered_count = MagicMock()
        mock_unclustered_count.scalar_one.return_value = 0

        # Mock result for total images count
        mock_images_count = MagicMock()
        mock_images_count.scalar_one.return_value = 0

        # Mock result for total L1 groups count
        mock_l1_count = MagicMock()
        mock_l1_count.scalar_one.return_value = 0

        override_db.execute = AsyncMock(
            side_effect=[
                mock_l2_result,
                mock_l2_count,
                mock_l1_result,
                mock_unclustered_count,
                mock_images_count,
                mock_l1_count,
            ]
        )

        response = client.get("/api/v1/clusters")
        assert response.status_code == 200
        data = response.json()
        assert data["l2_clusters"] == []
        assert data["unclustered_groups"] == []
        assert data["total_images"] == 0
        assert data["total_l1_groups"] == 0
        assert data["total_l2_clusters"] == 0
        assert data["total_unclustered_groups"] == 0
        assert data["offset"] == 0
        assert data["limit"] == 50

    def test_get_hierarchy_does_not_include_images(self, client, override_db):
        """Hierarchy groups should NOT contain nested images (N+1 fix)."""
        group = _make_l1_group(id=1, member_count=5)
        l2 = MagicMock()
        l2.id = 1
        l2.label = None
        l2.member_count = 1
        l2.total_images = 5
        l2.centroid_image_id = "img-1"
        l2.viz_x = 1.0
        l2.viz_y = 2.0
        l2.groups = [group]

        mock_l2_result = MagicMock()
        mock_l2_result.scalars.return_value.all.return_value = [l2]
        mock_l2_count = MagicMock()
        mock_l2_count.scalar_one.return_value = 1
        mock_l1_result = MagicMock()
        mock_l1_result.scalars.return_value.all.return_value = []
        mock_unclustered_count = MagicMock()
        mock_unclustered_count.scalar_one.return_value = 0
        mock_images_count = MagicMock()
        mock_images_count.scalar_one.return_value = 5
        mock_l1_count = MagicMock()
        mock_l1_count.scalar_one.return_value = 1

        override_db.execute = AsyncMock(
            side_effect=[
                mock_l2_result,
                mock_l2_count,
                mock_l1_result,
                mock_unclustered_count,
                mock_images_count,
                mock_l1_count,
            ]
        )

        response = client.get("/api/v1/clusters")
        assert response.status_code == 200
        data = response.json()
        cluster = data["l2_clusters"][0]
        group_data = cluster["groups"][0]
        # Brief schema should NOT have "images" key
        assert "images" not in group_data
        assert group_data["member_count"] == 5

    def test_get_hierarchy_unclustered_respects_offset(self, client, override_db):
        """Unclustered groups should respect pagination offset parameter."""
        executed_stmts: list[object] = []

        mock_l2_result = MagicMock()
        mock_l2_result.scalars.return_value.all.return_value = []
        mock_l2_count = MagicMock()
        mock_l2_count.scalar_one.return_value = 0
        mock_l1_result = MagicMock()
        mock_l1_result.scalars.return_value.all.return_value = []
        mock_unclustered_count = MagicMock()
        mock_unclustered_count.scalar_one.return_value = 0
        mock_images_count = MagicMock()
        mock_images_count.scalar_one.return_value = 0
        mock_l1_count = MagicMock()
        mock_l1_count.scalar_one.return_value = 0

        results = [
            mock_l2_result,
            mock_l2_count,
            mock_l1_result,
            mock_unclustered_count,
            mock_images_count,
            mock_l1_count,
        ]

        async def tracking_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            return results[len(executed_stmts) - 1]

        override_db.execute = AsyncMock(side_effect=tracking_execute)

        response = client.get("/api/v1/clusters?offset=5")
        assert response.status_code == 200
        # The 3rd query (index 2) is the unclustered groups query — verify it includes OFFSET
        unclustered_stmt = str(executed_stmts[2])
        assert "OFFSET" in unclustered_stmt.upper()

    def test_visualization_returns_actual_l1_group_id(self, client, override_db):
        """Visualization points should have actual l1_group_id, not hardcoded 0."""
        mock_result = MagicMock()
        # The query now returns (L2Cluster, l1_group_id) tuples
        cluster = MagicMock()
        cluster.centroid_image_id = "img-1"
        cluster.id = 1
        cluster.viz_x = 1.5
        cluster.viz_y = 2.5
        mock_result.all.return_value = [(cluster, 42)]
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/clusters/visualization")
        assert response.status_code == 200
        data = response.json()
        assert len(data["points"]) == 1
        assert data["points"][0]["l1_group_id"] == 42
        assert data["points"][0]["l2_cluster_id"] == 1

    def test_visualization_returns_none_l1_group_id_when_no_image(self, client, override_db):
        """Visualization point should have null l1_group_id when centroid image has no group."""
        mock_result = MagicMock()
        cluster = MagicMock()
        cluster.centroid_image_id = "img-orphan"
        cluster.id = 2
        cluster.viz_x = 3.0
        cluster.viz_y = 4.0
        mock_result.all.return_value = [(cluster, None)]
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/clusters/visualization")
        assert response.status_code == 200
        data = response.json()
        assert data["points"][0]["l1_group_id"] is None


@pytest.mark.unit
class TestSearchEndpoint:
    def test_search_similar_image_not_found(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.post(
            "/api/v1/search/similar",
            json={"image_id": "nonexistent", "n_results": 5},
        )
        assert response.status_code == 404

    def test_search_duplicates_no_hash(self, client, override_db):
        img = _make_image(phash=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.post(
            "/api/v1/search/duplicates",
            json={"image_id": "img-1", "max_distance": 5},
        )
        assert response.status_code == 400

    def test_search_similar_returns_400_when_query_has_no_embedding(self, client, override_db):
        img = _make_image(has_embedding=0)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        with patch("pic.api.search.find_similar_images", new_callable=AsyncMock) as mock_find:
            response = client.post(
                "/api/v1/search/similar",
                json={"image_id": "img-1", "n_results": 5},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Query image has no embedding yet"
        mock_find.assert_not_called()

    def test_search_duplicates_returns_400_for_invalid_query_phash(self, client, override_db):
        img = _make_image(phash="not-a-valid-hex-phash")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.post(
            "/api/v1/search/duplicates",
            json={"image_id": "img-1"},
        )

        assert response.status_code == 400
        assert "Invalid phash format in database" in response.json()["detail"]

    def test_search_duplicates_sql_based(self, client, override_db):
        """Duplicate search now uses SQL-side bit_count for Hamming distance."""
        query_img = _make_image(id="img-1", phash="f0e1d2c3b4a59687f0e1d2c3b4a59687f0e1d2c3b4a59687f0e1d2c3b4a59687")

        mock_query_result = MagicMock()
        mock_query_result.scalar_one_or_none.return_value = query_img
        # SQL query returns rows with named columns
        mock_sql_result = MagicMock()
        mock_sql_result.fetchall.return_value = []
        override_db.execute = AsyncMock(side_effect=[mock_query_result, mock_sql_result])

        response = client.post(
            "/api/v1/search/duplicates",
            json={"image_id": "img-1"},
        )

        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_search_duplicates_accepts_zero_threshold(self, client, override_db):
        query_img = _make_image(id="img-1", phash="f0e1d2c3b4a59687f0e1d2c3b4a59687f0e1d2c3b4a59687f0e1d2c3b4a59687")

        mock_query_result = MagicMock()
        mock_query_result.scalar_one_or_none.return_value = query_img
        mock_sql_result = MagicMock()
        mock_sql_result.fetchall.return_value = []
        override_db.execute = AsyncMock(side_effect=[mock_query_result, mock_sql_result])

        response = client.post(
            "/api/v1/search/duplicates",
            json={"image_id": "img-1", "threshold": 0},
        )

        assert response.status_code == 200
        assert response.json()["results"] == []


@pytest.mark.unit
class TestPipelineEndpoint:
    def test_run_pipeline_returns_202(self, client, override_db):
        from pic.models.db import JobStatus, JobType

        job = _make_job(type=JobType.PIPELINE, status=JobStatus.PENDING)
        mock_pending_result = MagicMock()
        mock_pending_result.scalar_one.return_value = 0
        override_db.execute = AsyncMock(return_value=mock_pending_result)
        override_db.add = MagicMock()
        override_db.commit = AsyncMock()

        # Mock refresh to set job attributes that will be validated
        async def mock_refresh(obj):
            obj.id = job.id
            obj.type = job.type
            obj.status = job.status
            obj.progress = 0.0
            obj.result = None
            obj.error = None
            obj.created_at = job.created_at
            obj.completed_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch("pic.api.pipeline.submit_pipeline_job", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = None
            response = client.post("/api/v1/pipeline/run", json={})
            assert response.status_code == 202
            assert override_db.add.called
            assert override_db.commit.called

    def test_run_pipeline_returns_location_header(self, client, override_db):
        """202 response should include Location header pointing to job."""
        from pic.models.db import JobStatus, JobType

        job = _make_job(id="job-xyz", type=JobType.PIPELINE, status=JobStatus.PENDING)
        mock_pending_result = MagicMock()
        mock_pending_result.scalar_one.return_value = 0
        override_db.execute = AsyncMock(return_value=mock_pending_result)
        override_db.add = MagicMock()
        override_db.commit = AsyncMock()

        async def mock_refresh(obj):
            obj.id = "job-xyz"
            obj.type = job.type
            obj.status = job.status
            obj.progress = 0.0
            obj.result = None
            obj.error = None
            obj.created_at = job.created_at
            obj.completed_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        with patch("pic.api.pipeline.submit_pipeline_job", new_callable=AsyncMock) as mock_submit:
            mock_submit.return_value = None
            response = client.post("/api/v1/pipeline/run", json={})
            assert response.status_code == 202
            assert response.headers.get("location") == "/api/v1/jobs/job-xyz"

    def test_run_pipeline_queue_full_returns_429(self, client, override_db):
        mock_pending_result = MagicMock()
        mock_pending_result.scalar_one.return_value = 100
        override_db.execute = AsyncMock(return_value=mock_pending_result)
        override_db.add = MagicMock()

        with patch("pic.api.pipeline.submit_pipeline_job", new_callable=AsyncMock):
            response = client.post("/api/v1/pipeline/run", json={})
            assert response.status_code == 429
            assert not override_db.add.called


@pytest.mark.unit
class TestProductsEndpoint:
    def test_create_product(self, client, override_db):
        group = _make_l1_group(representative_image_id="img-1")
        img1 = _make_image(id="img-1", l1_group_id=1)
        img1.product_id = None
        img2 = _make_image(id="img-2", l1_group_id=1)
        img2.product_id = None

        # Mock: find group, check no existing product, create, count
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = False
        mock_rep_exists_result = MagicMock()
        mock_rep_exists_result.scalar.return_value = True
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 2

        override_db.execute = AsyncMock(
            side_effect=[mock_group_result, mock_exists_result, mock_rep_exists_result, MagicMock(), mock_count_result]
        )
        override_db.add = MagicMock()
        override_db.flush = AsyncMock()
        override_db.commit = AsyncMock()

        async def mock_refresh(obj):
            obj.id = 1
            obj.representative_image_id = "img-1"
            obj.title = "Blue Widget"
            obj.description = "A widget"
            obj.tags = ["blue"]
            obj.created_at = datetime(2026, 1, 1)
            obj.updated_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        response = client.post(
            "/api/v1/products",
            json={"l1_group_id": 1, "title": "Blue Widget", "description": "A widget", "tags": ["blue"]},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Blue Widget"
        assert data["tags"] == ["blue"]
        assert data["image_count"] == 2

    def test_create_product_returns_location_header(self, client, override_db):
        """201 response should include Location header pointing to product."""
        group = _make_l1_group(representative_image_id="img-1")
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = False
        mock_rep_exists_result = MagicMock()
        mock_rep_exists_result.scalar.return_value = True
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        override_db.execute = AsyncMock(
            side_effect=[mock_group_result, mock_exists_result, mock_rep_exists_result, MagicMock(), mock_count_result]
        )
        override_db.add = MagicMock()
        override_db.flush = AsyncMock()
        override_db.commit = AsyncMock()

        async def mock_refresh(obj):
            obj.id = 42
            obj.representative_image_id = "img-1"
            obj.title = "Test"
            obj.description = None
            obj.tags = None
            obj.created_at = datetime(2026, 1, 1)
            obj.updated_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        response = client.post("/api/v1/products", json={"l1_group_id": 1, "title": "Test"})
        assert response.status_code == 201
        assert response.headers.get("location") == "/api/v1/products/42"

    def test_create_product_group_not_found(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.post(
            "/api/v1/products",
            json={"l1_group_id": 999},
        )
        assert response.status_code == 404

    def test_create_product_group_already_has_product(self, client, override_db):
        group = _make_l1_group()
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = True  # Already has product

        override_db.execute = AsyncMock(side_effect=[mock_group_result, mock_exists_result])

        response = client.post(
            "/api/v1/products",
            json={"l1_group_id": 1},
        )
        assert response.status_code == 409

    def test_create_product_missing_representative_image_rejected(self, client, override_db):
        group = _make_l1_group(representative_image_id="img-missing")
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = False
        mock_rep_exists_result = MagicMock()
        mock_rep_exists_result.scalar.return_value = False
        override_db.execute = AsyncMock(side_effect=[mock_group_result, mock_exists_result, mock_rep_exists_result])

        response = client.post("/api/v1/products", json={"l1_group_id": 1})
        assert response.status_code == 400
        assert response.json()["detail"] == "L1 group representative image not found"

    def test_list_products(self, client, override_db):
        product = _make_product()
        mock_result = MagicMock()
        mock_result.all.return_value = [(product, 2)]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/products")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["tags"] == ["blue", "widget"]
        assert data["items"][0]["image_count"] == 2

    def test_get_product(self, client, override_db):
        product = _make_product()
        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = product
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 2
        override_db.execute = AsyncMock(side_effect=[mock_product_result, mock_count])

        response = client.get("/api/v1/products/1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Blue Widget"
        assert data["tags"] == ["blue", "widget"]
        assert data["image_count"] == 2

    def test_get_product_not_found(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/products/999")
        assert response.status_code == 404

    def test_update_product(self, client, override_db):
        product = _make_product()
        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = product
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 2
        override_db.execute = AsyncMock(side_effect=[mock_product_result, mock_count])
        override_db.commit = AsyncMock()

        async def mock_refresh(obj, attribute_names=None):
            obj.title = "Updated Widget"
            obj.tags = ["new-tag"]

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        response = client.patch(
            "/api/v1/products/1",
            json={"title": "Updated Widget", "tags": ["new-tag"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Widget"
        assert data["tags"] == ["new-tag"]
        assert data["image_count"] == 2

    def test_delete_product(self, client, override_db):
        product = _make_product()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product
        override_db.execute = AsyncMock(return_value=mock_result)
        override_db.delete = AsyncMock()
        override_db.commit = AsyncMock()

        response = client.delete("/api/v1/products/1")
        assert response.status_code == 204

    def test_candidates_returns_groups_without_products(self, client, override_db):
        group1 = _make_l1_group(id=1, representative_image_id="img-1", member_count=5)
        group2 = _make_l1_group(id=2, representative_image_id="img-2", member_count=3)

        # The refactored candidates endpoint uses a JOIN, returning (group, s3_key) tuples
        mock_groups = MagicMock()
        mock_groups.all.return_value = [
            (group1, "processed/img1.jpg"),
            (group2, "processed/img2.jpg"),
        ]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 2

        override_db.execute = AsyncMock(side_effect=[mock_groups, mock_count])

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            response = client.get("/api/v1/products/candidates")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
            assert len(data["items"]) == 2
            assert data["items"][0]["l1_group_id"] == 1
            assert data["items"][0]["member_count"] == 5
            assert data["items"][0]["representative_url"] == "https://example.com/signed"

    def test_candidates_empty_when_all_have_products(self, client, override_db):
        mock_groups = MagicMock()
        mock_groups.all.return_value = []
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 0
        override_db.execute = AsyncMock(side_effect=[mock_groups, mock_count])

        response = client.get("/api/v1/products/candidates")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_product_images_returns_presigned_urls(self, client, override_db):
        product = _make_product(representative_image_id="img-1")
        img1 = _make_image(id="img-1", s3_key="processed/img1.jpg", s3_thumbnail_key="thumbs/img1.jpg")
        img2 = _make_image(id="img-2", s3_key="processed/img2.jpg")

        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = product
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 2
        mock_images_result = MagicMock()
        mock_images_result.scalars.return_value.all.return_value = [img1, img2]
        override_db.execute = AsyncMock(side_effect=[mock_product_result, mock_count_result, mock_images_result])

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            response = client.get("/api/v1/products/1/images")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 2
            assert len(data["items"]) == 2
            # First image is representative
            rep = next(item for item in data["items"] if item["image_id"] == "img-1")
            assert rep["is_representative"] is True
            assert rep["presigned_url"] == "https://example.com/signed"
            # Second image is not representative
            other = next(item for item in data["items"] if item["image_id"] == "img-2")
            assert other["is_representative"] is False

    def test_product_images_not_found(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/products/999/images")
        assert response.status_code == 404

    def test_create_product_empty_body(self, client, override_db):
        response = client.post("/api/v1/products", json={})
        assert response.status_code == 422

    def test_update_product_invalid_tags(self, client, override_db):
        response = client.patch("/api/v1/products/1", json={"tags": "not-a-list"})
        assert response.status_code == 422

    def test_create_product_uses_pessimistic_lock(self, client, override_db):
        """Product creation uses SELECT ... FOR UPDATE to prevent TOCTOU race."""
        group = _make_l1_group(representative_image_id="img-1")
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = False
        mock_rep_exists_result = MagicMock()
        mock_rep_exists_result.scalar.return_value = True
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        executed_stmts: list[object] = []

        async def tracking_execute(stmt, *args, **kwargs):
            executed_stmts.append(stmt)
            results = [mock_group_result, mock_exists_result, mock_rep_exists_result, MagicMock(), mock_count_result]
            return results[len(executed_stmts) - 1]

        override_db.execute = AsyncMock(side_effect=tracking_execute)
        override_db.add = MagicMock()
        override_db.flush = AsyncMock()
        override_db.commit = AsyncMock()

        async def mock_refresh(obj):
            obj.id = 1
            obj.representative_image_id = "img-1"
            obj.title = "Test"
            obj.description = None
            obj.tags = None
            obj.created_at = datetime(2026, 1, 1)
            obj.updated_at = None

        override_db.refresh = AsyncMock(side_effect=mock_refresh)

        response = client.post("/api/v1/products", json={"l1_group_id": 1, "title": "Test"})
        assert response.status_code == 201
        # First execute call should be the L1Group SELECT with FOR UPDATE
        first_stmt = str(executed_stmts[0])
        assert "FOR UPDATE" in first_stmt

    def test_create_product_integrity_error_returns_409(self, client, override_db):
        """IntegrityError during commit returns 409 for duplicate product race."""
        from sqlalchemy.exc import IntegrityError

        group = _make_l1_group(representative_image_id="img-1")
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = False
        mock_rep_exists_result = MagicMock()
        mock_rep_exists_result.scalar.return_value = True

        override_db.execute = AsyncMock(
            side_effect=[mock_group_result, mock_exists_result, mock_rep_exists_result, MagicMock()]
        )
        override_db.add = MagicMock()
        override_db.flush = AsyncMock()

        orig = Exception("duplicate key value violates unique constraint")
        orig.constraint_name = "ix_images_one_product_per_l1"  # type: ignore[attr-defined]
        exc = IntegrityError("", {}, orig)
        override_db.commit = AsyncMock(side_effect=exc)
        override_db.rollback = AsyncMock()

        response = client.post("/api/v1/products", json={"l1_group_id": 1, "title": "Test"})
        assert response.status_code == 409
        assert "already has a product" in response.json()["detail"]

    def test_create_product_missing_l1_group_id(self, client, override_db):
        """l1_group_id is required — omitting it yields 422."""
        response = client.post("/api/v1/products", json={"title": "Test"})
        assert response.status_code == 422

    def test_create_product_invalid_l1_group_id_type(self, client, override_db):
        """Non-integer l1_group_id yields 422."""
        response = client.post("/api/v1/products", json={"l1_group_id": "abc"})
        assert response.status_code == 422

    def test_create_product_tags_too_many(self, client, override_db):
        """More than 20 tags yields 422 via Pydantic validation."""
        response = client.post(
            "/api/v1/products",
            json={"l1_group_id": 1, "tags": [f"tag{i}" for i in range(21)]},
        )
        assert response.status_code == 422

    def test_create_product_tags_empty_string(self, client, override_db):
        """Empty string in tags list yields 422."""
        response = client.post(
            "/api/v1/products",
            json={"l1_group_id": 1, "tags": ["valid", ""]},
        )
        assert response.status_code == 422

    def test_create_product_tag_too_long(self, client, override_db):
        """Tag exceeding 100 chars yields 422."""
        response = client.post(
            "/api/v1/products",
            json={"l1_group_id": 1, "tags": ["x" * 101]},
        )
        assert response.status_code == 422

    def test_create_product_group_no_representative(self, client, override_db):
        """L1 group without representative image returns 400."""
        group = _make_l1_group(representative_image_id=None)
        mock_group_result = MagicMock()
        mock_group_result.scalar_one_or_none.return_value = group
        mock_exists_result = MagicMock()
        mock_exists_result.scalar.return_value = False

        override_db.execute = AsyncMock(side_effect=[mock_group_result, mock_exists_result])

        response = client.post("/api/v1/products", json={"l1_group_id": 1})
        assert response.status_code == 400
        assert "no representative image" in response.json()["detail"]

    def test_product_images_pagination(self, client, override_db):
        """Product images endpoint respects offset and limit pagination."""
        product = _make_product()
        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = product

        mock_total_result = MagicMock()
        mock_total_result.scalar_one.return_value = 5

        img = _make_image(id="img-3", s3_key="processed/img3.jpg")
        mock_images_result = MagicMock()
        mock_images_result.scalars.return_value.all.return_value = [img]

        override_db.execute = AsyncMock(side_effect=[mock_product_result, mock_total_result, mock_images_result])

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            response = client.get("/api/v1/products/1/images?offset=2&limit=1")
            assert response.status_code == 200
            data = response.json()
            assert data["offset"] == 2
            assert data["limit"] == 1
            assert data["total"] == 5
            assert len(data["items"]) == 1

    def test_product_images_empty_result(self, client, override_db):
        """Product with no images returns empty list."""
        product = _make_product()
        mock_product_result = MagicMock()
        mock_product_result.scalar_one_or_none.return_value = product

        mock_total_result = MagicMock()
        mock_total_result.scalar_one.return_value = 0

        mock_images_result = MagicMock()
        mock_images_result.scalars.return_value.all.return_value = []

        override_db.execute = AsyncMock(side_effect=[mock_product_result, mock_total_result, mock_images_result])

        with patch("pic.api.products.generate_presigned_url", return_value="https://example.com/signed"):
            response = client.get("/api/v1/products/1/images")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 0
            assert data["items"] == []


@pytest.mark.unit
class TestProductsAuth:
    def test_products_requires_auth(self):
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            with TestClient(app) as c:
                assert c.get("/api/v1/products").status_code == 401
                assert c.post("/api/v1/products", json={"l1_group_id": 1}).status_code == 401
                assert c.get("/api/v1/products/candidates").status_code == 401
                assert c.get("/api/v1/products/1/images").status_code == 401


@pytest.mark.unit
class TestCacheControlHeaders:
    """Verify Cache-Control middleware sets correct headers by path pattern."""

    def test_health_endpoint_has_no_cache(self, client):
        """GET /health should return Cache-Control: no-cache."""
        with patch("pic.main.engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

            response = client.get("/health")
            assert response.status_code == 200
            assert response.headers.get("Cache-Control") == "no-cache"

    def test_api_get_has_cache_control(self, client, override_db):
        """GET /api/v1/images should return a Cache-Control header with private, max-age."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images")
        assert response.status_code == 200
        cc = response.headers.get("Cache-Control")
        assert cc is not None
        assert "private" in cc

    def test_post_request_has_no_cache_control(self, client, override_db):
        """POST requests should not have a Cache-Control header."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.post(
            "/api/v1/search/similar",
            json={"image_id": "nonexistent", "n_results": 5},
        )
        # This returns 404 (error), so no Cache-Control should be set by our middleware
        assert response.headers.get("Cache-Control") is None

    def test_file_endpoint_has_long_cache(self, client, override_db):
        """GET /api/v1/images/{id}/file should return Cache-Control: private, max-age=300."""
        img = _make_image(id="img-1", s3_key="processed/photo.jpg")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = img
        override_db.execute = AsyncMock(return_value=mock_result)

        with patch("pic.api.images.generate_presigned_url", return_value="https://example.com/signed"):
            response = client.get("/api/v1/images/img-1/file")
            assert response.status_code == 200
            assert response.headers.get("Cache-Control") == "private, max-age=300"

    def test_error_response_has_no_cache_control(self, client, override_db):
        """Error responses (4xx) should not get Cache-Control headers from middleware."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/images/nonexistent")
        assert response.status_code == 404
        assert response.headers.get("Cache-Control") is None


@pytest.mark.unit
class TestRFC7807ErrorResponses:
    def test_404_returns_problem_detail(self, client, override_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/images/nonexistent-id")
        assert response.status_code == 404
        data = response.json()
        assert data["type"] == "about:blank"
        assert data["title"] == "Not Found"
        assert data["status"] == 404
        assert "detail" in data
        assert "instance" in data

    def test_422_returns_problem_detail_with_errors(self, client):
        # Send invalid data to trigger validation error
        response = client.post("/api/v1/clusters/run", json={"l2_min_cluster_size": -1})
        assert response.status_code == 422
        data = response.json()
        assert data["type"] == "about:blank"
        assert data["title"] == "Unprocessable Entity"
        assert data["status"] == 422
        assert "errors" in data


@pytest.mark.unit
class TestETagSupport:
    def test_get_returns_etag_header(self, client, override_db):
        """GET endpoints should return an ETag header."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images")
        assert response.status_code == 200
        etag = response.headers.get("etag")
        assert etag is not None
        assert etag.startswith('"')
        assert etag.endswith('"')

    def test_conditional_get_returns_304(self, client, override_db):
        """GET with matching If-None-Match should return 304."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        # First request to get the ETag
        response1 = client.get("/api/v1/images")
        assert response1.status_code == 200
        etag = response1.headers.get("etag")
        assert etag is not None

        # Reset mock for second request
        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.all.return_value = [img]
        mock_count2 = MagicMock()
        mock_count2.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result2, mock_count2])

        # Second request with If-None-Match
        response2 = client.get("/api/v1/images", headers={"If-None-Match": etag})
        assert response2.status_code == 304

    def test_conditional_get_returns_200_when_etag_mismatch(self, client, override_db):
        """GET with non-matching If-None-Match should return 200."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 1
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images", headers={"If-None-Match": '"stale-etag"'})
        assert response.status_code == 200
        assert response.headers.get("etag") is not None

    def test_error_responses_have_no_etag(self, client, override_db):
        """Error responses should not have ETag headers."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        override_db.execute = AsyncMock(return_value=mock_result)

        response = client.get("/api/v1/images/nonexistent")
        assert response.status_code == 404
        assert response.headers.get("etag") is None


@pytest.mark.unit
class TestPaginationLinks:
    def test_list_images_includes_pagination_links(self, client, override_db):
        """GET /api/v1/images should include pagination links."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 100
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images?offset=10&limit=5")
        assert response.status_code == 200
        data = response.json()
        links = data["links"]
        assert links is not None
        assert "self" in links
        assert "next" in links
        assert "prev" in links
        assert "first" in links
        assert "offset=10" in links["self"]
        assert "offset=15" in links["next"]
        assert "offset=5" in links["prev"]
        assert "offset=0" in links["first"]

    def test_pagination_links_no_next_on_last_page(self, client, override_db):
        """When on the last page, next should be None."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 3
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images?offset=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        links = data["links"]
        assert links["next"] is None
        assert links["prev"] is None

    def test_pagination_links_last_field(self, client, override_db):
        """Links should include a 'last' link to the final page."""
        img = _make_image()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [img]
        mock_count = MagicMock()
        mock_count.scalar_one.return_value = 25
        override_db.execute = AsyncMock(side_effect=[mock_result, mock_count])

        response = client.get("/api/v1/images?offset=0&limit=10")
        assert response.status_code == 200
        data = response.json()
        links = data["links"]
        assert links["last"] is not None
        assert "offset=20" in links["last"]


@pytest.mark.unit
class TestClusterViewEndpoint:
    def test_view_returns_html(self, client, override_db):
        """GET /clusters/view should return HTML with cluster visualization."""
        with (
            patch(
                "pic.api.clusters.generate_visualization_html",
                return_value="<html><body>test</body></html>",
            ),
        ):
            response = client.get("/api/v1/clusters/view")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "<html>" in response.text

    def test_view_requires_api_key_header(self):
        """With API key configured, /clusters/view requires X-API-Key header."""
        with patch("pic.core.auth.settings") as mock_settings:
            mock_settings.api_key = "secret-key"
            from pic.main import app

            with TestClient(app) as c:
                response = c.get("/api/v1/clusters/view")
                assert response.status_code == 401
