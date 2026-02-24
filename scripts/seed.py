#!/usr/bin/env python3
"""Bulk upload images from a local directory to S3, wait for processing, then cluster.

Usage:
    python scripts/seed.py /path/to/images/
    python scripts/seed.py /path/to/images/ --no-cluster   # Skip auto-clustering

Uploads all image files to the S3 bucket configured in .env,
under the images/ prefix. The S3 event trigger will automatically
process each uploaded image. After all images are processed,
triggers the clustering pipeline and waits for completion.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import modal

# Load settings
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from pic.config import settings  # noqa: E402
from pic.services.image_store import get_s3_client  # noqa: E402

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}
POLL_INTERVAL_SECONDS = 30
INGEST_TIMEOUT_SECONDS = 3600  # 1 hour max wait for ingestion
CLUSTER_TIMEOUT_SECONDS = 3600  # 1 hour max wait for clustering


def _get_sync_db_url() -> str:
    """Convert async DB URL to sync psycopg2 format."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def _count_pending_images(conn) -> int:  # noqa: ANN001
    """Count images that exist in DB but don't have embeddings yet."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM images WHERE has_embedding = 0")
        return cur.fetchone()[0]


def _create_image_record(conn, image_id: str, filename: str, s3_key: str, file_size: int) -> None:  # noqa: ANN001
    """Insert image metadata into the database."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO images (id, filename, s3_key, file_size, has_embedding) "
            "VALUES (%s, %s, %s, %s, 0) ON CONFLICT (id) DO NOTHING",
            (image_id, filename, s3_key, file_size),
        )
    conn.commit()


def _wait_for_ingestion(conn, total_uploaded: int) -> bool:  # noqa: ANN001
    """Poll DB until all images have embeddings. Returns True on success."""
    print(f"\nWaiting for {total_uploaded} images to finish processing...")
    start = time.time()

    while time.time() - start < INGEST_TIMEOUT_SECONDS:
        pending = _count_pending_images(conn)
        elapsed = int(time.time() - start)
        if pending == 0:
            print(f"  All images processed! ({elapsed}s elapsed)")
            return True
        print(f"  {pending} images still processing... ({elapsed}s elapsed)")
        time.sleep(POLL_INTERVAL_SECONDS)

    print(f"  Timed out after {INGEST_TIMEOUT_SECONDS}s with {_count_pending_images(conn)} images still pending.")
    return False


def _submit_clustering(conn) -> str | None:  # noqa: ANN001
    """Create a Job record and submit a Modal clustering job. Returns job_id."""
    job_id = str(uuid.uuid4())

    # Create Job record in DB
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (id, type, status, progress) VALUES (%s, %s, %s, %s)",
            (job_id, "CLUSTER_FULL", "PENDING", 0.0),
        )
    conn.commit()

    # Trigger Modal clustering function
    fn = modal.Function.from_name("nic", "run_cluster")
    call = fn.spawn(job_id, None)
    print(f"Submitted clustering job {job_id[:8]} (Modal: {call.object_id})")
    return job_id


def _wait_for_clustering(conn, job_id: str) -> bool:  # noqa: ANN001
    """Poll the Job record until clustering completes. Returns True on success."""
    print("Waiting for clustering to complete...")
    start = time.time()

    while time.time() - start < CLUSTER_TIMEOUT_SECONDS:
        with conn.cursor() as cur:
            cur.execute("SELECT status, progress, result, error FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()

        if row is None:
            print("  Job record not found!")
            return False

        status, progress, result, error = row
        elapsed = int(time.time() - start)

        if status == "COMPLETED":
            summary = json.loads(result) if result else {}
            print(f"  Clustering complete! ({elapsed}s elapsed)")
            print(f"    Images:      {summary.get('total_images', '?')}")
            print(f"    L1 groups:   {summary.get('l1_groups', '?')}")
            print(f"    L2 clusters: {summary.get('l2_clusters', '?')}")
            print(f"    L2 noise:    {summary.get('l2_noise_groups', '?')}")
            return True

        if status == "FAILED":
            print(f"  Clustering FAILED: {error}")
            return False

        print(f"  Status: {status}, progress: {progress:.0%} ({elapsed}s elapsed)")
        time.sleep(POLL_INTERVAL_SECONDS)

    print(f"  Timed out after {CLUSTER_TIMEOUT_SECONDS}s")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk upload images and trigger clustering")
    parser.add_argument("directory", help="Directory containing images to upload")
    parser.add_argument("--no-cluster", action="store_true", help="Skip auto-clustering after upload")
    args = parser.parse_args()

    source_dir = Path(args.directory)
    if not source_dir.is_dir():
        print(f"Error: {source_dir} is not a directory")
        sys.exit(1)

    s3 = get_s3_client()
    bucket = settings.s3_bucket

    # Find all image files
    image_files = []
    for f in sorted(source_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            image_files.append(f)

    if not image_files:
        print(f"No image files found in {source_dir}")
        sys.exit(0)

    print(f"Found {len(image_files)} images in {source_dir}")
    print(f"Uploading to {bucket}/images/")

    # Connect to DB for creating image records + triggering ingest
    import psycopg2

    conn = psycopg2.connect(_get_sync_db_url())
    ingest_fn = modal.Function.from_name("nic", "run_ingest")

    try:
        for i, filepath in enumerate(image_files, 1):
            image_id = str(uuid.uuid4())
            s3_key = f"images/{filepath.name}"
            content_type = _get_content_type(filepath.suffix)
            file_size = filepath.stat().st_size

            # Upload to R2
            s3.upload_file(
                str(filepath),
                bucket,
                s3_key,
                ExtraArgs={"ContentType": content_type},
            )

            # Create DB record
            _create_image_record(conn, image_id, filepath.name, s3_key, file_size)

            # Trigger Modal ingest (non-blocking)
            ingest_fn.spawn(image_id)

            print(f"  [{i}/{len(image_files)}] {filepath.name} → {bucket}/{s3_key}")

        print(f"\nUploaded {len(image_files)} images, ingest jobs spawned.")

        if args.no_cluster:
            print("Skipping clustering (--no-cluster). Run POST /api/v1/clusters/run when ready.")
            return

        # Wait for all ingest jobs to finish, then cluster
        if not _wait_for_ingestion(conn, len(image_files)):
            print("Ingestion did not complete. Skipping clustering.")
            sys.exit(1)

        job_id = _submit_clustering(conn)
        if not _wait_for_clustering(conn, job_id):
            sys.exit(1)

        print("\nDone! All images uploaded, processed, and clustered.")
    finally:
        conn.close()


def _get_content_type(ext: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }.get(ext.lower(), "application/octet-stream")


if __name__ == "__main__":
    main()
