#!/usr/bin/env python3
"""One-off script to re-run clustering with updated L1 HDBSCAN algorithm.

Usage:
    uv run python scripts/recluster_now.py
    uv run python scripts/recluster_now.py --epsilon 0.15  # custom epsilon
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

# Add src/ to path so nic package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


async def main(epsilon: float | None, min_cluster_size: int | None, min_samples: int | None) -> None:
    from pic.core.database import async_session
    from pic.services.clustering_pipeline import run_full_clustering

    params: dict[str, Any] = {}
    if epsilon is not None:
        params["l1_cluster_selection_epsilon"] = epsilon
    if min_cluster_size is not None:
        params["l1_min_cluster_size"] = min_cluster_size
    if min_samples is not None:
        params["l1_min_samples"] = min_samples

    print(f"Running full clustering (params={params})...")
    async with async_session() as db:
        stats = await run_full_clustering(db, params)

    print(f"Done! Stats: {dict(stats)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-run clustering with L1 HDBSCAN")
    parser.add_argument("--epsilon", type=float, default=None, help="L1 cluster_selection_epsilon")
    parser.add_argument("--min-cluster-size", type=int, default=None, help="L1 min_cluster_size")
    parser.add_argument("--min-samples", type=int, default=None, help="L1 min_samples")
    args = parser.parse_args()
    asyncio.run(main(args.epsilon, args.min_cluster_size, args.min_samples))
