import logging

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from umap import UMAP

from nic.config import settings

logger = logging.getLogger(__name__)


def cluster_level1(
    image_ids: list[str],
    embeddings: np.ndarray,
    cluster_selection_epsilon: float | None = None,
    min_cluster_size: int | None = None,
    min_samples: int | None = None,
) -> dict[int, list[str]]:
    """
    Level 1: Group similar images using HDBSCAN on cosine distance.

    Uses density-based clustering which avoids the transitive chaining problem
    of connected components — images are grouped by local density rather than
    by a simple pairwise threshold.

    Returns {group_id: [image_id, ...]}.
    """
    _epsilon = (
        cluster_selection_epsilon if cluster_selection_epsilon is not None else settings.l1_cluster_selection_epsilon
    )
    _min_cluster_size = min_cluster_size if min_cluster_size is not None else settings.l1_min_cluster_size
    _min_samples = min_samples if min_samples is not None else settings.l1_min_samples
    n = len(image_ids)

    if n == 0:
        return {}

    if n == 1:
        return {0: [image_ids[0]]}

    logger.info(
        "Running L1 HDBSCAN clustering on %d images (min_cluster_size=%d, min_samples=%d, epsilon=%.3f)",
        n,
        _min_cluster_size,
        _min_samples,
        _epsilon,
    )

    clusterer = HDBSCAN(
        min_cluster_size=_min_cluster_size,
        min_samples=_min_samples,
        metric="cosine",
        cluster_selection_epsilon=_epsilon,
    )
    labels = clusterer.fit_predict(embeddings)

    # Build groups: clustered images get a group, noise points (-1) each become singletons
    groups: dict[int, list[str]] = {}
    next_group_id = 0
    cluster_to_group: dict[int, int] = {}

    for idx, label in enumerate(labels):
        if label == -1:
            # Noise point → singleton group
            groups[next_group_id] = [image_ids[idx]]
            next_group_id += 1
        else:
            if label not in cluster_to_group:
                cluster_to_group[label] = next_group_id
                next_group_id += 1
            gid = cluster_to_group[label]
            groups.setdefault(gid, []).append(image_ids[idx])

    logger.info("L1 clustering: %d images → %d groups", n, len(groups))
    return groups


def select_representative(
    group_image_ids: list[str],
    all_image_ids: list[str],
    all_embeddings: np.ndarray,
) -> str:
    """Select the image closest to the group centroid as the representative."""
    if len(group_image_ids) == 1:
        return group_image_ids[0]

    # Get indices of group members in the full embedding array
    id_to_idx = {img_id: idx for idx, img_id in enumerate(all_image_ids)}
    indices = [id_to_idx[img_id] for img_id in group_image_ids if img_id in id_to_idx]

    if not indices:
        return group_image_ids[0]

    group_embeddings = all_embeddings[indices]
    centroid = group_embeddings.mean(axis=0)

    # Find closest to centroid
    distances = np.linalg.norm(group_embeddings - centroid, axis=1)
    closest_idx = indices[int(np.argmin(distances))]
    return all_image_ids[closest_idx]


def _reduce_dimensions(embeddings: np.ndarray, n: int) -> np.ndarray:
    """UMAP dimensionality reduction from high-D embeddings to clustering space."""
    n_neighbors = min(settings.l2_umap_n_neighbors, n - 1)
    n_components = min(settings.l2_umap_n_components, n - 2) if n > settings.l2_umap_n_components + 1 else max(2, n - 2)

    reducer = UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    return reducer.fit_transform(embeddings)  # type: ignore[no-any-return]


def _cluster_reduced(reduced: np.ndarray, min_cluster_size: int, min_samples: int) -> np.ndarray:
    """HDBSCAN density-based clustering on UMAP-reduced embeddings."""
    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    return clusterer.fit_predict(reduced)  # type: ignore[no-any-return]


def _compute_viz_coords(reduced: np.ndarray) -> np.ndarray:
    """PCA projection from UMAP space to 2D for visualization."""
    n_pca_components = min(2, reduced.shape[1])
    pca = PCA(n_components=n_pca_components, random_state=42)
    return pca.fit_transform(reduced)  # type: ignore[no-any-return]


def cluster_level2(
    embeddings: np.ndarray,
    group_ids: list[int],
    min_cluster_size: int | None = None,
    min_samples: int | None = None,
) -> dict[str, object]:
    """
    Level 2: Cluster representative images into semantic groups.
    Returns dict with clusters, labels, 2D coordinates, and stats.
    """
    _min_cluster_size = min_cluster_size or settings.l2_min_cluster_size
    _min_samples = min_samples or settings.l2_min_samples

    if _min_cluster_size < 2:
        raise ValueError(f"min_cluster_size must be >= 2, got {_min_cluster_size}")
    if _min_samples < 1:
        raise ValueError(f"min_samples must be >= 1, got {_min_samples}")
    if _min_samples > _min_cluster_size:
        raise ValueError(f"min_samples ({_min_samples}) must be <= min_cluster_size ({_min_cluster_size})")
    n = len(group_ids)

    if n < _min_cluster_size:
        logger.warning("Too few groups (%d) for L2 clustering (min=%d)", n, _min_cluster_size)
        return {
            "clusters": {-1: group_ids},
            "labels": [-1] * n,
            "coordinates_2d": [[0.0, 0.0]] * n,
            "n_clusters": 0,
            "n_noise": n,
        }

    logger.info(
        "Running L2 clustering: %d representatives, min_cluster=%d, min_samples=%d",
        n,
        _min_cluster_size,
        _min_samples,
    )

    reduced = _reduce_dimensions(embeddings, n)
    labels = _cluster_reduced(reduced, _min_cluster_size, _min_samples)
    coords_2d = _compute_viz_coords(reduced)

    # Build cluster dict
    clusters: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        clusters.setdefault(int(label), []).append(group_ids[idx])

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int(np.sum(labels == -1))

    logger.info("L2 clustering: %d groups → %d clusters, %d noise", n, n_clusters, n_noise)

    return {
        "clusters": clusters,
        "labels": labels.tolist(),
        "coordinates_2d": coords_2d.tolist(),
        "n_clusters": n_clusters,
        "n_noise": n_noise,
    }
