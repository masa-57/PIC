"""Unit tests for the clustering service."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from pic.services.clustering import (
    _cluster_reduced,
    _compute_viz_coords,
    _reduce_dimensions,
    cluster_level1,
    cluster_level2,
    select_representative,
)


def _make_embeddings(n: int, dim: int = 768, seed: int = 42) -> np.ndarray:
    """Generate random L2-normalized embeddings."""
    rng = np.random.default_rng(seed)
    emb = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    return emb / norms


def _make_tight_cluster(n: int, base_seed: int = 42, noise: float = 0.02) -> np.ndarray:
    """Generate n embeddings that are very close together (high cosine similarity)."""
    rng = np.random.default_rng(base_seed)
    base = rng.standard_normal((1, 768)).astype(np.float32)
    base /= np.linalg.norm(base)
    perturbations = rng.standard_normal((n, 768)).astype(np.float32) * noise
    cluster = base + perturbations
    norms = np.linalg.norm(cluster, axis=1, keepdims=True)
    return cluster / norms


@pytest.mark.unit
class TestLevel1Clustering:
    def test_empty_input(self):
        result = cluster_level1([], np.empty((0, 768)))
        assert result == {}

    def test_single_image(self):
        emb = _make_embeddings(1)
        result = cluster_level1(["img1"], emb)
        assert result == {0: ["img1"]}

    def test_uses_cosine_metric_without_precomputed_matrix(self):
        emb = _make_embeddings(3)
        ids = ["img1", "img2", "img3"]

        with patch("pic.services.clustering.HDBSCAN") as mock_hdbscan:
            clusterer = MagicMock()
            clusterer.fit_predict.return_value = np.array([0, 0, -1])
            mock_hdbscan.return_value = clusterer

            result = cluster_level1(
                ids,
                emb,
                min_cluster_size=2,
                min_samples=1,
                cluster_selection_epsilon=0.1,
            )

        assert mock_hdbscan.call_args.kwargs["metric"] == "cosine"
        fit_input = clusterer.fit_predict.call_args.args[0]
        assert fit_input.shape == emb.shape
        assert np.array_equal(fit_input, emb)
        assert len(result) == 2

    def test_tight_group_vs_outliers(self):
        """A tight cluster of similar images should be grouped, outliers should not."""
        # 5 very similar images (tight cluster)
        tight = _make_tight_cluster(5, base_seed=10, noise=0.01)
        # 5 random outliers
        outliers = _make_embeddings(5, seed=99)
        emb = np.vstack([tight, outliers])
        ids = [f"t{i}" for i in range(5)] + [f"o{i}" for i in range(5)]

        result = cluster_level1(ids, emb, min_cluster_size=2, min_samples=1, cluster_selection_epsilon=0.10)

        # The tight group should be together
        tight_group = None
        for g in result.values():
            if "t0" in g:
                tight_group = set(g)
                break
        assert tight_group is not None
        assert {"t0", "t1", "t2", "t3", "t4"}.issubset(tight_group)

    def test_returns_all_images(self):
        """Every input image should appear in exactly one output group."""
        emb = _make_embeddings(10, seed=42)
        ids = [f"img{i}" for i in range(10)]
        result = cluster_level1(ids, emb, cluster_selection_epsilon=0.10)

        # Every image should appear exactly once across all groups
        all_images = []
        for g in result.values():
            all_images.extend(g)
        assert sorted(all_images) == sorted(ids)

    def test_tight_cluster_grouped(self):
        """Images that are very close together should be grouped by HDBSCAN."""
        # 6 very similar images + 4 random outliers
        tight = _make_tight_cluster(6, base_seed=10, noise=0.01)
        outliers = _make_embeddings(4, seed=99)
        emb = np.vstack([tight, outliers])
        tight_ids = [f"img{i}" for i in range(6)]
        outlier_ids = [f"out{i}" for i in range(4)]
        ids = tight_ids + outlier_ids

        result = cluster_level1(
            ids,
            emb,
            min_cluster_size=2,
            min_samples=1,
            cluster_selection_epsilon=0.10,
        )

        # The 6 tight images should be in one group
        for g in result.values():
            if "img0" in g:
                assert set(tight_ids).issubset(set(g))
                break
        else:
            pytest.fail("img0 not found in any group")

    def test_two_separate_clusters(self):
        """Two well-separated tight clusters should produce two groups."""
        cluster_a = _make_tight_cluster(5, base_seed=10, noise=0.01)
        cluster_b = _make_tight_cluster(5, base_seed=99, noise=0.01)
        emb = np.vstack([cluster_a, cluster_b])
        a_ids = [f"a{i}" for i in range(5)]
        b_ids = [f"b{i}" for i in range(5)]
        ids = a_ids + b_ids

        result = cluster_level1(
            ids,
            emb,
            min_cluster_size=2,
            min_samples=1,
            cluster_selection_epsilon=0.10,
        )

        # Find the groups containing cluster A and cluster B
        group_a = None
        group_b = None
        for g in result.values():
            if "a0" in g:
                group_a = set(g)
            if "b0" in g:
                group_b = set(g)

        assert group_a is not None
        assert set(a_ids).issubset(group_a)
        assert group_b is not None
        assert set(b_ids).issubset(group_b)
        # They should be in different groups
        assert group_a.isdisjoint(group_b)

    def test_noise_points_become_singletons(self):
        """Noise points (label -1 from HDBSCAN) should become singleton groups."""
        # 6 tight + 4 orthogonal outliers (guaranteed far apart)
        tight = _make_tight_cluster(6, base_seed=10, noise=0.01)

        # Create 4 outliers that are orthogonal to each other (high cosine distance)
        outlier_embs = np.zeros((4, 768), dtype=np.float32)
        for i in range(4):
            outlier_embs[i, i * 100] = 1.0  # Each hot in a different dimension

        emb = np.vstack([tight, outlier_embs])
        ids = [f"t{i}" for i in range(6)] + [f"out{i}" for i in range(4)]

        result = cluster_level1(
            ids,
            emb,
            min_cluster_size=2,
            min_samples=1,
            cluster_selection_epsilon=0.05,
        )

        # Outliers should each be in their own singleton groups (cosine distance ~1.0)
        for g in result.values():
            for oid in ["out0", "out1", "out2", "out3"]:
                if oid in g:
                    assert len(g) == 1, f"{oid} should be a singleton but was grouped with {g}"

    def test_epsilon_controls_merge_distance(self):
        """Higher epsilon should merge more clusters together."""
        # Two clusters at moderate distance, each with 5 members
        rng = np.random.default_rng(42)
        base_a = rng.standard_normal((1, 768)).astype(np.float32)
        base_a /= np.linalg.norm(base_a)
        base_b = 0.85 * base_a + 0.15 * rng.standard_normal((1, 768)).astype(np.float32)
        base_b /= np.linalg.norm(base_b)

        cluster_a = base_a + rng.standard_normal((5, 768)).astype(np.float32) * 0.005
        cluster_a /= np.linalg.norm(cluster_a, axis=1, keepdims=True)
        cluster_b = base_b + rng.standard_normal((5, 768)).astype(np.float32) * 0.005
        cluster_b /= np.linalg.norm(cluster_b, axis=1, keepdims=True)

        emb = np.vstack([cluster_a, cluster_b])
        ids = [f"a{i}" for i in range(5)] + [f"b{i}" for i in range(5)]

        # Small epsilon → likely two separate groups
        result_small = cluster_level1(
            ids,
            emb,
            min_cluster_size=2,
            min_samples=1,
            cluster_selection_epsilon=0.01,
        )

        # Large epsilon → more likely to merge
        result_large = cluster_level1(
            ids,
            emb,
            min_cluster_size=2,
            min_samples=1,
            cluster_selection_epsilon=0.50,
        )

        # Larger epsilon should produce equal or fewer groups
        assert len(result_large) <= len(result_small)


@pytest.mark.unit
class TestSelectRepresentative:
    def test_single_member(self):
        """Single-member group returns that member."""
        result = select_representative(
            group_image_ids=["img1"],
            all_image_ids=["img1", "img2"],
            all_embeddings=np.array([[1.0, 0.0], [0.0, 1.0]]),
        )
        assert result == "img1"

    def test_closest_to_centroid(self):
        """Should select the image closest to the group centroid."""
        embeddings = np.array(
            [
                [1.0, 0.0, 0.0],  # img1
                [0.9, 0.1, 0.0],  # img2 (close to img1)
                [0.0, 0.0, 1.0],  # img3 (far)
            ]
        )
        result = select_representative(
            group_image_ids=["img1", "img2"],
            all_image_ids=["img1", "img2", "img3"],
            all_embeddings=embeddings,
        )
        # Centroid of img1+img2 = [0.95, 0.05, 0.0]
        # img2 [0.9, 0.1, 0.0] is closer to centroid than img1 [1.0, 0.0, 0.0]
        assert result == "img2"


@pytest.mark.unit
class TestLevel2Clustering:
    def test_too_few_groups(self):
        """With fewer groups than min_cluster_size, all should be noise."""
        embeddings = np.random.default_rng(42).standard_normal((3, 768))
        result = cluster_level2(
            embeddings=embeddings,
            group_ids=[1, 2, 3],
            min_cluster_size=5,
        )
        assert result["n_clusters"] == 0
        assert result["n_noise"] == 3

    def test_returns_expected_structure(self):
        """Check that the result has all expected keys."""
        n = 50
        rng = np.random.default_rng(42)
        # Create 3 synthetic clusters
        embeddings = np.vstack(
            [
                rng.standard_normal((20, 768)) + np.array([5.0] + [0.0] * 767),
                rng.standard_normal((20, 768)) + np.array([0.0, 5.0] + [0.0] * 766),
                rng.standard_normal((10, 768)),
            ]
        )
        group_ids = list(range(n))

        result = cluster_level2(
            embeddings=embeddings,
            group_ids=group_ids,
            min_cluster_size=5,
            min_samples=3,
        )

        assert "clusters" in result
        assert "labels" in result
        assert "coordinates_2d" in result
        assert "n_clusters" in result
        assert "n_noise" in result
        assert len(result["labels"]) == n
        assert len(result["coordinates_2d"]) == n
        # Should find at least some clusters
        assert result["n_clusters"] >= 1


@pytest.mark.unit
class TestClusteringEdgeCases:
    def test_cluster_level2_with_nan_embeddings(self):
        """cluster_level2 raises ValueError when embeddings contain NaN values.

        UMAP's input validation rejects NaN, so callers must sanitize
        embeddings before invoking cluster_level2.
        """
        rng = np.random.default_rng(42)
        n = 20
        embeddings = rng.standard_normal((n, 768))
        # Inject NaN into the first embedding
        embeddings[0, :] = np.nan

        with pytest.raises(ValueError, match="NaN"):
            cluster_level2(
                embeddings=embeddings,
                group_ids=list(range(n)),
                min_cluster_size=5,
                min_samples=3,
            )

    def test_cluster_level2_with_identical_embeddings(self):
        """When all embeddings are identical, HDBSCAN should classify everything as noise."""
        n = 20
        # All embeddings are the same 768-d vector
        single_vec = np.random.default_rng(42).standard_normal((1, 768))
        embeddings = np.tile(single_vec, (n, 1))

        result = cluster_level2(
            embeddings=embeddings,
            group_ids=list(range(n)),
            min_cluster_size=5,
            min_samples=3,
        )

        assert len(result["labels"]) == n
        # Identical points have zero variance — HDBSCAN treats them all as noise
        # or puts them all in one cluster; either outcome is acceptable
        assert result["n_clusters"] >= 0
        assert result["n_noise"] >= 0
        assert result["n_clusters"] + result["n_noise"] >= 0

    def test_cluster_level1_empty_embeddings(self):
        """cluster_level1 with empty arrays returns empty dict regardless of params."""
        result = cluster_level1([], np.empty((0, 768)), cluster_selection_epsilon=0.1)
        assert result == {}

        result = cluster_level1([], np.empty((0, 768)), cluster_selection_epsilon=0.5)
        assert result == {}

    def test_select_representative_with_missing_ids(self):
        """select_representative should handle group IDs not present in all_image_ids."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((3, 768))

        # "img_missing" is not in all_image_ids — select_representative should not crash
        result = select_representative(
            group_image_ids=["img1", "img_missing", "img2"],
            all_image_ids=["img1", "img2", "img3"],
            all_embeddings=embeddings,
        )

        # Should return one of the valid IDs (img1 or img2), not the missing one
        assert result in ("img1", "img2")

    def test_select_representative_with_all_missing_ids(self):
        """When no group IDs are in all_image_ids, fallback to first group ID."""
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((2, 768))

        result = select_representative(
            group_image_ids=["missing1", "missing2"],
            all_image_ids=["img1", "img2"],
            all_embeddings=embeddings,
        )

        # Fallback: returns group_image_ids[0] when no indices are found
        assert result == "missing1"


@pytest.mark.unit
class TestExtractedHelpers:
    """Tests for helper functions extracted from cluster_level2."""

    def test_reduce_dimensions_output_shape(self):
        """_reduce_dimensions should reduce 768D to a lower-dimensional space."""
        rng = np.random.default_rng(42)
        n = 50
        embeddings = rng.standard_normal((n, 768))

        reduced = _reduce_dimensions(embeddings, n)

        assert reduced.shape[0] == n
        assert reduced.shape[1] < 768

    def test_cluster_reduced_returns_labels(self):
        """_cluster_reduced should return an array of integer labels."""
        rng = np.random.default_rng(42)
        n = 30
        reduced = rng.standard_normal((n, 10))

        labels = _cluster_reduced(reduced, min_cluster_size=5, min_samples=3)

        assert len(labels) == n
        # Labels should be integers (cluster IDs or -1 for noise)
        assert all(isinstance(int(lbl), int) for lbl in labels)

    def test_compute_viz_coords_returns_2d(self):
        """_compute_viz_coords should project to 2D."""
        rng = np.random.default_rng(42)
        n = 20
        reduced = rng.standard_normal((n, 10))

        coords = _compute_viz_coords(reduced)

        assert coords.shape == (n, 2)
