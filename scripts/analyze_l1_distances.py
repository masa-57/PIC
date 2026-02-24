#!/usr/bin/env python3
"""Analyze pHash Hamming + embedding cosine distance distributions.

Helps determine the right L1 clustering threshold by showing where
natural gaps exist in the distance distribution.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import psycopg2
from dotenv import load_dotenv
from scipy.spatial.distance import pdist, squareform

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DB_URL = os.environ["NIC_POSTGRES_URL"]


def main() -> None:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Fetch all pHash hex strings
    cur.execute("SELECT id, phash FROM images WHERE phash IS NOT NULL ORDER BY id")
    rows = cur.fetchall()
    ids = [r[0] for r in rows]
    phashes = [r[1] for r in rows]
    n = len(ids)
    print(f"Loaded {n} images with pHash\n")

    # Convert hex → bit arrays
    bit_rows = []
    for h in phashes:
        byte_arr = np.array([int(h[i : i + 2], 16) for i in range(0, len(h), 2)], dtype=np.uint8)
        bit_rows.append(np.unpackbits(byte_arr))
    bit_array = np.array(bit_rows, dtype=np.uint8)

    # Pairwise Hamming distances
    condensed = pdist(bit_array, metric="hamming") * bit_array.shape[1]
    distances = condensed.astype(int)

    print("=== pHash Hamming Distance Distribution ===")
    print(f"Total pairs: {len(distances)}")
    print(
        f"Min: {distances.min()}, Max: {distances.max()}, "
        f"Mean: {distances.mean():.1f}, Median: {np.median(distances):.1f}"
    )
    print()

    # Histogram by bucket
    buckets = [0, 5, 10, 12, 15, 20, 25, 30, 35, 40, 50, 60, 80, 100, 128, 256]
    print(f"{'Range':>12} | {'Count':>7} | {'Cumul%':>7} | Histogram")
    print("-" * 70)
    total = len(distances)
    cumul = 0
    for i in range(len(buckets) - 1):
        lo, hi = buckets[i], buckets[i + 1]
        count = int(np.sum((distances >= lo) & (distances < hi)))
        cumul += count
        pct = cumul / total * 100
        bar = "#" * max(1, int(count / total * 200))
        print(f"  [{lo:>3}-{hi:>3}) | {count:>7} | {pct:>6.1f}% | {bar}")

    # Show how many L1 groups at different thresholds
    print("\n=== L1 Group Count at Various Thresholds ===")
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    dist_matrix = squareform(condensed)
    np.fill_diagonal(dist_matrix, 999)

    for thresh in [10, 12, 15, 18, 20, 25, 30, 35, 40, 50]:
        rows_arr, cols_arr = np.where(dist_matrix <= thresh)
        if len(rows_arr) == 0:
            n_groups = n
        else:
            data = np.ones(len(rows_arr), dtype=np.int8)
            adj = csr_matrix((data, (rows_arr, cols_arr)), shape=(n, n))
            n_groups, _ = connected_components(adj, directed=False)
        _ = n_groups  # used below via labels
        # Get actual group sizes
        _, labels = connected_components(
            csr_matrix(
                (
                    np.ones(max(1, len(rows_arr)), dtype=np.int8),
                    (rows_arr[: max(1, len(rows_arr))], cols_arr[: max(1, len(rows_arr))]),
                ),
                shape=(n, n),
            )
            if len(rows_arr) > 0
            else csr_matrix((n, n)),
            directed=False,
        )
        sizes = np.bincount(labels)
        n_singleton = int(np.sum(sizes == 1))
        n_multi = int(np.sum(sizes > 1))
        max_size = int(sizes.max())
        print(
            f"  threshold={thresh:>2}: {n_groups:>4} groups ({n_singleton} singletons, "
            f"{n_multi} multi-image, largest={max_size})"
        )

    # Now check embedding cosine similarity for the closest pHash pairs
    print("\n=== Top 30 Closest pHash Pairs (candidates for grouping) ===")
    flat_idx = np.argsort(distances)[:30]
    # Convert flat condensed index to (i, j) pairs
    for rank, fi in enumerate(flat_idx):
        # Reverse condensed index formula
        i = int(n - 2 - int(np.floor(np.sqrt(-8 * fi + 4 * n * (n - 1) - 7) / 2.0 - 0.5)))
        j = int(fi + i + 1 - n * (n - 1) // 2 + (n - i) * ((n - i) - 1) // 2)
        dist = int(distances[fi])
        fn_i = ids[i][:8]
        fn_j = ids[j][:8]
        print(f"  #{rank + 1:>2}: {fn_i}..{fn_j}  hamming={dist}")

    conn.close()


if __name__ == "__main__":
    main()
