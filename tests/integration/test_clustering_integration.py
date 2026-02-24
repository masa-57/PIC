"""Integration tests for the clustering pipeline with real PostgreSQL (TC-3)."""

import uuid
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import func, select

from nic.models.db import Image, L1Group, L2Cluster
from nic.services.clustering_pipeline import run_full_clustering


@pytest.mark.integration
class TestClusteringPipelineIntegration:
    """Run clustering pipeline against real DB (mock only the ML functions)."""

    async def _seed_images_with_embeddings(self, db, count: int, phash_prefix: str = "aa") -> list[str]:
        """Insert images with deterministic embeddings."""
        ids = []
        for i in range(count):
            img_id = str(uuid.uuid4())
            rng = np.random.default_rng(seed=i + 100)
            vec = rng.standard_normal(768).astype(float)
            vec = (vec / np.linalg.norm(vec)).tolist()

            img = Image(
                id=img_id,
                filename=f"img_{i}.jpg",
                s3_key=f"processed/img_{i}.jpg",
                content_hash=img_id[:64],
                phash=f"{phash_prefix}{i:014x}",
                embedding=vec,
                has_embedding=1,
            )
            db.add(img)
            ids.append(img_id)
        await db.commit()
        return ids

    async def test_empty_db_returns_zeros(self, db):
        stats = await run_full_clustering(db, {})
        assert stats["total_images"] == 0
        assert stats["l1_groups"] == 0
        assert stats["l2_clusters"] == 0
        assert stats["l2_noise_groups"] == 0

    async def test_pipeline_creates_l1_groups(self, db):
        """Pipeline creates L1 groups and assigns images."""
        ids = await self._seed_images_with_embeddings(db, count=4)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            # 2 L1 groups: [img0, img1] and [img2, img3]
            mock_l1.return_value = {0: [ids[0], ids[1]], 1: [ids[2], ids[3]]}
            mock_rep.side_effect = lambda group_ids, *a: group_ids[0]
            mock_l2.return_value = {
                "clusters": {-1: [1, 2]},
                "labels": [-1, -1],
                "coordinates_2d": [[0.0, 0.0], [1.0, 1.0]],
                "n_clusters": 0,
                "n_noise": 2,
            }

            stats = await run_full_clustering(db, {})

        assert stats["total_images"] == 4
        assert stats["l1_groups"] == 2

        # Verify L1 groups in DB
        result = await db.execute(select(func.count()).select_from(L1Group))
        assert result.scalar_one() == 2

        # Verify images are assigned to L1 groups
        result = await db.execute(select(Image).where(Image.l1_group_id.isnot(None)))
        assigned = result.scalars().all()
        assert len(assigned) == 4

    async def test_pipeline_creates_l2_clusters(self, db):
        """Pipeline creates L2 clusters and links L1 groups."""
        ids = await self._seed_images_with_embeddings(db, count=6)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            # 3 L1 groups, each with 2 images
            mock_l1.return_value = {
                0: [ids[0], ids[1]],
                1: [ids[2], ids[3]],
                2: [ids[4], ids[5]],
            }
            mock_rep.side_effect = lambda group_ids, *a: group_ids[0]

            # L2: groups 1,2 form a cluster, group 3 is noise
            # Note: cluster_level2 receives DB group IDs (auto-incremented),
            # which we can't predict. We'll use the mock to return what we need.
            def fake_l2(embeddings, group_ids, **kwargs):
                return {
                    "clusters": {0: [group_ids[0], group_ids[1]], -1: [group_ids[2]]},
                    "labels": [0, 0, -1],
                    "coordinates_2d": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
                    "n_clusters": 1,
                    "n_noise": 1,
                }

            mock_l2.side_effect = fake_l2

            stats = await run_full_clustering(db, {})

        assert stats["l2_clusters"] == 1
        assert stats["l2_noise_groups"] == 1

        # Verify L2 cluster exists in DB
        result = await db.execute(select(func.count()).select_from(L2Cluster))
        assert result.scalar_one() == 1

        # Verify L1 groups are linked to L2 cluster
        result = await db.execute(select(L1Group).where(L1Group.l2_cluster_id.isnot(None)))
        linked = result.scalars().all()
        assert len(linked) == 2

    async def test_pipeline_cleans_previous_clustering(self, db):
        """Re-running clustering clears old L1/L2 data before creating new."""
        ids = await self._seed_images_with_embeddings(db, count=2)

        # First run: creates 2 L1 groups
        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {0: [ids[0]], 1: [ids[1]]}
            mock_rep.side_effect = lambda g, *a: g[0]
            mock_l2.return_value = {
                "clusters": {-1: [1, 2]},
                "labels": [-1, -1],
                "coordinates_2d": [[0.0, 0.0], [1.0, 1.0]],
                "n_clusters": 0,
                "n_noise": 2,
            }
            await run_full_clustering(db, {})

        count1 = (await db.execute(select(func.count()).select_from(L1Group))).scalar_one()
        assert count1 == 2

        # Second run: creates 1 L1 group (all in one)
        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {0: [ids[0], ids[1]]}
            mock_rep.return_value = ids[0]
            mock_l2.return_value = {
                "clusters": {-1: [1]},
                "labels": [-1],
                "coordinates_2d": [[0.0, 0.0]],
                "n_clusters": 0,
                "n_noise": 1,
            }
            await run_full_clustering(db, {})

        count2 = (await db.execute(select(func.count()).select_from(L1Group))).scalar_one()
        assert count2 == 1  # Old groups deleted, new one created

    async def test_l2_cluster_stores_viz_coordinates(self, db):
        """L2 cluster stores centroid coordinates for visualization."""
        ids = await self._seed_images_with_embeddings(db, count=4)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {i: [ids[i]] for i in range(4)}
            mock_rep.side_effect = lambda g, *a: g[0]

            def fake_l2(embeddings, group_ids, **kwargs):
                return {
                    "clusters": {0: group_ids[:4]},
                    "labels": [0, 0, 0, 0],
                    "coordinates_2d": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]],
                    "n_clusters": 1,
                    "n_noise": 0,
                }

            mock_l2.side_effect = fake_l2
            await run_full_clustering(db, {})

        result = await db.execute(select(L2Cluster))
        cluster = result.scalar_one()
        assert cluster.viz_x is not None
        assert cluster.viz_y is not None
        # Average of [1,3,5,7] = 4.0 and [2,4,6,8] = 5.0
        assert abs(cluster.viz_x - 4.0) < 0.01
        assert abs(cluster.viz_y - 5.0) < 0.01


@pytest.mark.integration
class TestVectorStoreIntegration:
    """Test vector store operations with real pgvector."""

    async def test_find_similar_images(self, db):
        """find_similar_images returns results ordered by cosine similarity."""
        from nic.services.vector_store import find_similar_images

        # Create images with known embeddings
        base_vec = np.zeros(768)
        base_vec[0] = 1.0  # Unit vector along first axis

        query_id = str(uuid.uuid4())
        db.add(
            Image(
                id=query_id,
                filename="query.jpg",
                s3_key="q.jpg",
                embedding=base_vec.tolist(),
                has_embedding=1,
            )
        )

        # Similar to query (small perturbation)
        similar_vec = base_vec.copy()
        similar_vec[1] = 0.1
        similar_vec = similar_vec / np.linalg.norm(similar_vec)
        similar_id = str(uuid.uuid4())
        db.add(
            Image(
                id=similar_id,
                filename="similar.jpg",
                s3_key="s.jpg",
                embedding=similar_vec.tolist(),
                has_embedding=1,
            )
        )

        # Dissimilar to query (orthogonal)
        dissimilar_vec = np.zeros(768)
        dissimilar_vec[500] = 1.0
        dissimilar_id = str(uuid.uuid4())
        db.add(
            Image(
                id=dissimilar_id,
                filename="dissimilar.jpg",
                s3_key="d.jpg",
                embedding=dissimilar_vec.tolist(),
                has_embedding=1,
            )
        )
        await db.commit()

        results = await find_similar_images(db, image_id=query_id, n_results=10)

        assert len(results) == 2
        # Similar image should be first (higher score = closer to 1)
        assert results[0].image_id == similar_id
        assert results[0].score > results[1].score
        assert results[0].score > 0.9  # Very similar

    async def test_find_similar_with_no_embedding(self, db):
        """Image without embedding returns empty results."""
        from nic.services.vector_store import find_similar_images

        img_id = str(uuid.uuid4())
        db.add(Image(id=img_id, filename="no_embed.jpg", s3_key="n.jpg", has_embedding=0))
        await db.commit()

        results = await find_similar_images(db, image_id=img_id, n_results=5)
        assert results == []

    async def test_get_all_embeddings(self, db):
        """get_all_embeddings returns IDs and vectors for embedded images."""
        from nic.services.vector_store import get_all_embeddings

        # Add 3 images: 2 with embeddings, 1 without
        for i in range(2):
            rng = np.random.default_rng(seed=i)
            vec = rng.standard_normal(768).astype(float)
            vec = (vec / np.linalg.norm(vec)).tolist()
            db.add(
                Image(
                    id=str(uuid.uuid4()),
                    filename=f"e{i}.jpg",
                    s3_key=f"e{i}.jpg",
                    embedding=vec,
                    has_embedding=1,
                )
            )
        db.add(
            Image(
                id=str(uuid.uuid4()),
                filename="no_e.jpg",
                s3_key="no_e.jpg",
                has_embedding=0,
            )
        )
        await db.commit()

        ids, embeddings = await get_all_embeddings(db)
        assert len(ids) == 2
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 768
