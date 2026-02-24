"""Shared clustering pipeline logic used by both cluster and pipeline workers."""

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nic.models.db import Image, L1Group, L2Cluster
from nic.models.schemas import ClusteringStats
from nic.services.clustering import cluster_level1, cluster_level2, select_representative

logger = logging.getLogger(__name__)

_IN_CLAUSE_BATCH_SIZE = 5000


async def _batched_update(
    db: AsyncSession,
    table: type,
    column: Any,  # InstrumentedAttribute or ColumnElement
    ids: Sequence[Any],
    values: dict[str, Any],
) -> None:
    """Execute UPDATE ... WHERE col IN (...) in batches to avoid plan instability."""
    for i in range(0, len(ids), _IN_CLAUSE_BATCH_SIZE):
        batch = ids[i : i + _IN_CLAUSE_BATCH_SIZE]
        await db.execute(update(table).where(column.in_(batch)).values(**values))


async def run_full_clustering(db: AsyncSession, params: dict[str, Any]) -> ClusteringStats:
    """Run L1 + L2 clustering on all images with embeddings.

    Returns dict with clustering stats: l1_groups, l2_clusters, l2_noise_groups, total_images.
    """
    # Load only needed columns (PERF-6: avoids loading filename, s3_key, timestamps etc.)
    result = await db.execute(select(Image.id, Image.embedding).where(Image.embedding.isnot(None)))
    rows = result.all()

    if not rows:
        logger.warning("No images with embeddings found, nothing to cluster")
        return ClusteringStats(total_images=0, l1_groups=0, l2_clusters=0, l2_noise_groups=0)

    image_ids = [r.id for r in rows]
    embeddings_array = np.array([r.embedding for r in rows], dtype=np.float32)

    logger.info("Clustering %d images", len(rows))

    # ── Level 1: Near-duplicate grouping (HDBSCAN on cosine distance) ──
    l1_groups = cluster_level1(
        image_ids=image_ids,
        embeddings=embeddings_array,
        cluster_selection_epsilon=params.get("l1_cluster_selection_epsilon"),
        min_cluster_size=params.get("l1_min_cluster_size"),
        min_samples=params.get("l1_min_samples"),
    )

    try:
        # Clear existing L1 groups (bulk DELETE instead of loop)
        await db.execute(update(Image).values(l1_group_id=None))
        await db.execute(delete(L1Group))

        # Create L1 groups in DB
        for _local_id, member_ids in l1_groups.items():
            representative = select_representative(member_ids, image_ids, embeddings_array)
            group = L1Group(
                representative_image_id=representative,
                member_count=len(member_ids),
            )
            db.add(group)
            await db.flush()

            # Bulk UPDATE in batches to avoid unbounded IN clause
            await _batched_update(db, Image, Image.id, member_ids, {"l1_group_id": group.id})

        await db.flush()
        logger.info("Created %d L1 groups", len(l1_groups))

        # ── Level 2: Semantic clustering ──
        # Project only needed columns to avoid loading full ORM objects (PERF-5)
        group_result = await db.execute(
            select(L1Group.id, L1Group.representative_image_id, L1Group.member_count).where(
                L1Group.representative_image_id.isnot(None)
            )
        )
        db_group_rows = group_result.all()
        rep_image_ids = [r.representative_image_id for r in db_group_rows]
        group_db_ids = [r.id for r in db_group_rows]

        id_to_idx = {img_id: idx for idx, img_id in enumerate(image_ids)}
        rep_embeddings = np.array([embeddings_array[id_to_idx[img_id]] for img_id in rep_image_ids], dtype=np.float32)

        # Clear existing L2 clusters (bulk DELETE instead of loop)
        await db.execute(update(L1Group).values(l2_cluster_id=None))
        await db.execute(delete(L2Cluster))

        l2_result = cluster_level2(
            embeddings=rep_embeddings,
            group_ids=group_db_ids,
            min_cluster_size=params.get("l2_min_cluster_size"),
            min_samples=params.get("l2_min_samples"),
        )

        # Create L2 clusters in DB
        coords_2d: list[list[float]] = l2_result["coordinates_2d"]  # type: ignore[assignment]
        group_to_coords: dict[int, tuple[float, float]] = {}
        for idx, group_id in enumerate(group_db_ids):
            group_to_coords[group_id] = (coords_2d[idx][0], coords_2d[idx][1])

        # Dict lookup for O(1) group resolution instead of O(n^2) nested loop
        group_by_id = {r.id: r for r in db_group_rows}

        clusters_map: dict[int, list[int]] = l2_result["clusters"]  # type: ignore[assignment]
        for cluster_label, member_group_ids in clusters_map.items():
            if cluster_label == -1:
                continue  # Skip noise

            total_images = sum(group_by_id[g_id].member_count for g_id in member_group_ids if g_id in group_by_id)

            centroid_group = max(
                (group_by_id[g_id] for g_id in member_group_ids if g_id in group_by_id),
                key=lambda g: g.member_count,
            )

            cluster_coords = [group_to_coords[g_id] for g_id in member_group_ids if g_id in group_to_coords]
            avg_x = sum(c[0] for c in cluster_coords) / len(cluster_coords) if cluster_coords else 0.0
            avg_y = sum(c[1] for c in cluster_coords) / len(cluster_coords) if cluster_coords else 0.0

            cluster = L2Cluster(
                member_count=len(member_group_ids),
                total_images=total_images,
                centroid_image_id=centroid_group.representative_image_id,
                viz_x=avg_x,
                viz_y=avg_y,
            )
            db.add(cluster)
            await db.flush()

            # Bulk UPDATE in batches to avoid unbounded IN clause
            await _batched_update(db, L1Group, L1Group.id, member_group_ids, {"l2_cluster_id": cluster.id})

        await db.commit()
    except Exception:
        # Ensure all destructive L1/L2 changes are rolled back on any mid-run failure.
        await db.rollback()
        logger.exception("Clustering failed; rolled back L1/L2 changes")
        raise

    n_clusters: int = l2_result["n_clusters"]  # type: ignore[assignment]
    n_noise: int = l2_result["n_noise"]  # type: ignore[assignment]
    stats = ClusteringStats(
        total_images=len(rows),
        l1_groups=len(l1_groups),
        l2_clusters=n_clusters,
        l2_noise_groups=n_noise,
    )
    logger.info("Clustering complete: %s", stats)
    return stats
