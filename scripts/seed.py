#!/usr/bin/env python3
"""Upload a folder of images to PIC storage and run the pipeline.

Usage:
    python scripts/seed.py /path/to/images/
    python scripts/seed.py /path/to/images/ --api http://localhost:8000 --no-cluster

Copies images into the storage backend's ``images/`` inbox (S3, GCS or local,
per your PIC_* settings), then calls ``POST /api/v1/pipeline/run`` and waits
for the job to finish. With docker compose and local storage you can skip this
script and copy files into ``data/images/`` directly.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from pic.config import settings  # noqa: E402
from pic.core.constants import IMAGE_EXTENSIONS, S3_PREFIX_INBOX  # noqa: E402
from pic.services.storage import get_storage_backend  # noqa: E402
from pic.services.storage.base import StorageBackend  # noqa: E402

POLL_INTERVAL_SECONDS = 5.0
TIMEOUT_SECONDS = 3600.0
TERMINAL_STATUSES = {"completed", "failed"}
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def find_images(directory: Path) -> list[Path]:
    """All image files under ``directory``, sorted by name."""
    files = [p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(files, key=lambda p: p.name)


def upload_images(files: list[Path], storage: StorageBackend) -> int:
    """Upload each file to ``images/<name>``. Returns the number uploaded."""
    for i, path in enumerate(files, 1):
        key = f"{S3_PREFIX_INBOX}{path.name}"
        storage.upload(key, path.read_bytes(), CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
        print(f"  [{i}/{len(files)}] {path.name} -> {key}")
    return len(files)


def start_pipeline(client: httpx.Client) -> str:
    """Trigger the pipeline and return its job ID."""
    response = client.post("/api/v1/pipeline/run", json={})
    response.raise_for_status()
    return str(response.json()["id"])


def wait_for_job(
    client: httpx.Client,
    job_id: str,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = TIMEOUT_SECONDS,
) -> str:
    """Poll the job until it completes or fails. Returns the final status."""
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/api/v1/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in TERMINAL_STATUSES:
            if job["status"] == "failed":
                print(f"Job {job_id} failed: {job.get('error')}")
            return str(job["status"])
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Job {job_id} still {job['status']} after {timeout:.0f}s")
        time.sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload images and run the PIC pipeline")
    parser.add_argument("directory", type=Path, help="Directory containing images")
    parser.add_argument("--api", default="http://localhost:8000", help="PIC API base URL")
    parser.add_argument("--no-cluster", action="store_true", help="Upload only; do not run the pipeline")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory")
        return 1
    files = find_images(args.directory)
    if not files:
        print(f"No image files found in {args.directory}")
        return 0

    print(f"Uploading {len(files)} images to the {settings.storage_backend} storage inbox")
    upload_images(files, get_storage_backend())
    if args.no_cluster:
        print("Skipping the pipeline (--no-cluster). Run POST /api/v1/pipeline/run when ready.")
        return 0

    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    with httpx.Client(base_url=args.api, headers=headers, timeout=30) as client:
        job_id = start_pipeline(client)
        print(f"Pipeline job {job_id} started; waiting for it to finish...")
        status = wait_for_job(client, job_id)
    print(f"Pipeline job {job_id}: {status}")
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
