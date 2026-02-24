#!/usr/bin/env python3
"""Analyze DINOv2 embedding cosine similarity distribution for L1 grouping."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import psycopg2
from dotenv import load_dotenv
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import pdist, squareform

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DB_URL = os.environ["NIC_POSTGRES_URL"]


def main() -> None:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, embedding
        FROM images
        WHERE embedding IS NOT NULL AND has_embedding = 1
        ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()

    ids = [r[0] for r in rows]

    # pgvector returns "[0.1,0.2,...]" string — parse it
    def parse_vec(v: str | list) -> list[float]:
        if isinstance(v, list):
            return v
        return [float(x) for x in v.strip("[]").split(",")]

    embeddings = np.array([parse_vec(r[1]) for r in rows])
    n = len(ids)
    print(f"Loaded {n} images with embeddings (dim={embeddings.shape[1]})\n")

    # Cosine distance (1 - cosine_similarity)
    cosine_dists = pdist(embeddings, metric="cosine")
    similarities = 1.0 - cosine_dists  # cosine similarity

    print("=== Embedding Cosine Similarity Distribution ===")
    print(f"Total pairs: {len(similarities)}")
    print(
        f"Min sim: {similarities.min():.4f}, Max sim: {similarities.max():.4f}, "
        f"Mean: {similarities.mean():.4f}, Median: {np.median(similarities):.4f}"
    )
    print()

    # Histogram
    buckets = [0.0, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.92, 0.95, 0.98, 1.01]
    print(f"{'Sim Range':>14} | {'Count':>7} | {'Cumul%':>7} | Histogram")
    print("-" * 75)
    total = len(similarities)
    cumul = 0
    for i in range(len(buckets) - 1):
        lo, hi = buckets[i], buckets[i + 1]
        count = int(np.sum((similarities >= lo) & (similarities < hi)))
        cumul += count
        pct = cumul / total * 100
        bar = "#" * max(1, int(count / total * 200))
        print(f"  [{lo:.2f}-{hi:.2f}) | {count:>7} | {pct:>6.1f}% | {bar}")

    # Group count at various cosine similarity thresholds
    print("\n=== L1 Group Count at Various Cosine Similarity Thresholds ===")
    dist_matrix = squareform(cosine_dists)
    np.fill_diagonal(dist_matrix, 999)

    for sim_thresh in [0.98, 0.95, 0.92, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60]:
        dist_thresh = 1.0 - sim_thresh  # cosine distance threshold
        rows_arr, cols_arr = np.where(dist_matrix <= dist_thresh)
        if len(rows_arr) == 0:
            n_groups = n
            labels = np.arange(n)
        else:
            data = np.ones(len(rows_arr), dtype=np.int8)
            adj = csr_matrix((data, (rows_arr, cols_arr)), shape=(n, n))
            n_groups, labels = connected_components(adj, directed=False)
        sizes = np.bincount(labels)
        n_singleton = int(np.sum(sizes == 1))
        n_multi = int(np.sum(sizes > 1))
        max_size = int(sizes.max())
        avg_multi = float(sizes[sizes > 1].mean()) if n_multi > 0 else 0
        print(
            f"  cosine>={sim_thresh:.2f}: {n_groups:>4} groups "
            f"({n_singleton} single, {n_multi} multi, largest={max_size}, avg_multi={avg_multi:.1f})"
        )

    # Show top 30 most similar pairs by embedding
    print("\n=== Top 30 Most Similar Image Pairs (by Embedding) ===")
    flat_idx = np.argsort(cosine_dists)[:30]
    for rank, fi in enumerate(flat_idx):
        i = int(n - 2 - int(np.floor(np.sqrt(-8 * fi + 4 * n * (n - 1) - 7) / 2.0 - 0.5)))
        j = int(fi + i + 1 - n * (n - 1) // 2 + (n - i) * ((n - i) - 1) // 2)
        sim = float(similarities[fi])
        print(f"  #{rank + 1:>2}: {ids[i][:8]}..{ids[j][:8]}  cosine_sim={sim:.4f}")


if __name__ == "__main__":
    main()
