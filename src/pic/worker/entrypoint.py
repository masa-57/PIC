"""AWS Batch job entry point. Dispatches to ingest or cluster tasks."""

import argparse
import asyncio
import logging
import sys

from pic.core.logging import setup_logging


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="NIC Worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Process an uploaded image")
    ingest_parser.add_argument("--image-id", required=True)

    # Cluster command
    cluster_parser = subparsers.add_parser("cluster", help="Run clustering pipeline")
    cluster_parser.add_argument("--job-id", required=True)
    cluster_parser.add_argument("--params", default=None, help="JSON params override")

    args = parser.parse_args()

    if args.command == "ingest":
        from pic.worker.ingest import run_ingest

        logger.info("Starting ingest for image %s", args.image_id)
        asyncio.run(run_ingest(args.image_id))
    elif args.command == "cluster":
        from pic.worker.cluster import run_cluster

        logger.info("Starting clustering for job %s", args.job_id)
        asyncio.run(run_cluster(args.job_id, args.params))
    else:
        logger.error("Unknown command: %s", args.command)
        sys.exit(1)


if __name__ == "__main__":
    main()
