#!/usr/bin/env python3
"""Analyze HDBSCAN parameters for L1 clustering on production data."""

import os
from collections import Counter

import numpy as np
import psycopg2
from sklearn.cluster import HDBSCAN
from sklearn.metrics.pairwise import cosine_distances

DB_URL = os.environ["NIC_POSTGRES_URL"]


def parse_vec(s: str) -> np.ndarray:
    return np.array([float(x) for x in s.strip("[]").split(",")])


def main() -> None:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT i.id, i.filename, i.embedding FROM images i WHERE i.embedding IS NOT NULL ORDER BY i.id")
    rows = cur.fetchall()
    conn.close()

    names = [r[1] for r in rows]
    embs = np.array([parse_vec(r[2]) for r in rows])
    print(f"{len(embs)} images loaded")

    dist_matrix = cosine_distances(embs)

    # Find our test pair
    cake_350_idx = names.index("IMG_4291-Photoroom.jpeg")
    cake_379_idx = names.index("IMG_4295-Photoroom.jpeg")
    pair_dist = dist_matrix[cake_350_idx, cake_379_idx]
    print(f"Cake pair cosine distance: {pair_dist:.4f} (similarity: {1 - pair_dist:.4f})")
    print()

    header = (
        f"{'min_clust':>9} | {'min_samp':>8} | {'epsilon':>7} | "
        f"{'Groups':>6} | {'Noise/Sing':>10} | {'Largest':>7} | "
        f"{'Multi':>5} | Cake?"
    )
    print(header)
    print("-" * len(header))

    for min_cluster in [2, 3]:
        for min_samples in [1, 2]:
            for eps in [0.0, 0.10, 0.15, 0.20, 0.25, 0.30]:
                clusterer = HDBSCAN(
                    min_cluster_size=min_cluster,
                    min_samples=min_samples,
                    metric="precomputed",
                    cluster_selection_epsilon=eps,
                )
                labels = clusterer.fit_predict(dist_matrix)

                counts = Counter(labels)
                noise = counts.pop(-1, 0)
                n_clusters = len(counts)
                total_groups = n_clusters + noise
                largest = max(counts.values()) if counts else 0
                multi = sum(1 for c in counts.values() if c > 1)

                l350 = labels[cake_350_idx]
                l379 = labels[cake_379_idx]
                cake_ok = l350 == l379 and l350 != -1

                print(
                    f"{min_cluster:9d} | {min_samples:8d} | {eps:7.2f} | "
                    f"{total_groups:6d} | {noise:10d} | {largest:7d} | "
                    f"{multi:5d} | {'YES' if cake_ok else 'no'}"
                )
        print()


if __name__ == "__main__":
    main()
