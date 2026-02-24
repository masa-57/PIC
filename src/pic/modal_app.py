"""Modal app definition for PIC GPU workers (ingest + clustering)."""

import modal

app = modal.App("pic")

# Container image with all dependencies (core + ML)
pic_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        # Core
        "sqlalchemy[asyncio]>=2.0,<3.0",
        "asyncpg>=0.30,<1.0",
        "pgvector>=0.3,<1.0",
        "boto3>=1.35,<2.0",
        "pydantic-settings>=2.0,<3.0",
        "imagehash>=4.3,<5.0",
        "Pillow>=10.0,<12.0",
        "numpy>=1.26,<3.0",
        "tenacity>=8.0,<10.0",
        "prometheus-client>=0.20,<1.0",
        # Google Drive
        "google-api-python-client>=2.0,<3.0",
        "google-auth>=2.0,<3.0",
        # ML
        "torch>=2.2,<3.0",
        "transformers>=4.40,<5.0",
        "scikit-learn>=1.4,<2.0",
        "umap-learn>=0.5.7,<1.0",
        "numba>=0.59,<1.0",
        "scipy>=1.12,<2.0",
    )
    .add_local_python_source("pic")
)

# Lightweight image for GDrive file check (no ML deps — fast cold start ~5s)
pic_check_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "sqlalchemy[asyncio]>=2.0,<3.0",
        "asyncpg>=0.30,<1.0",
        "pgvector>=0.3,<1.0",
        "pydantic-settings>=2.0,<3.0",
        "google-api-python-client>=2.0,<3.0",
        "google-auth>=2.0,<3.0",
        "tenacity>=8.0,<10.0",
    )
    .add_local_python_source("pic")
)


async def _has_inflight_gdrive_sync_job() -> bool:
    """Return True if a GDRIVE_SYNC job is already pending or running."""
    from sqlalchemy import func, select

    from pic.core.database import async_session
    from pic.models.db import Job, JobStatus, JobType

    async with async_session() as db:
        result = await db.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.type == JobType.GDRIVE_SYNC,
                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
        )
        return result.scalar_one() > 0


async def _check_gdrive_for_new_files_impl() -> None:
    import logging

    from pic.config import settings

    logger = logging.getLogger(__name__)

    if not settings.gdrive_folder_id or not settings.gdrive_service_account_json:
        return

    from pic.services.gdrive import build_drive_service, list_image_files

    service = build_drive_service(settings.gdrive_service_account_json)
    files = list_image_files(service, settings.gdrive_folder_id)
    if not files:
        return

    if await _has_inflight_gdrive_sync_job():
        logger.info("GDrive sync already pending/running, skipping GPU worker spawn")
        return

    logger.info("Found %d new files in Google Drive, spawning GPU worker", len(files))

    try:
        fn = modal.Function.from_name("pic", "sync_gdrive_to_r2")
        fn.spawn()
    except Exception:
        logger.exception("Failed to spawn GPU worker for GDrive sync")


@app.function(
    image=pic_image,
    gpu="T4",
    memory=8192,
    timeout=1800,
    max_containers=5,
    retries=modal.Retries(max_retries=2, backoff_coefficient=2.0, initial_delay=5.0),
    secrets=[modal.Secret.from_name("pic-env")],
)
async def run_ingest(image_id: str) -> None:
    """Process an uploaded image: compute pHash + DINOv2 embedding."""
    from pic.worker.ingest import run_ingest as _run_ingest

    await _run_ingest(image_id)


@app.function(
    image=pic_image,
    gpu="T4",
    memory=8192,
    timeout=1800,
    max_containers=1,
    retries=modal.Retries(max_retries=1, backoff_coefficient=2.0, initial_delay=10.0),
    secrets=[modal.Secret.from_name("pic-env")],
)
async def run_cluster(job_id: str, params_json: str | None = None) -> None:
    """Run L1 + L2 clustering pipeline."""
    from pic.worker.cluster import run_cluster as _run_cluster

    await _run_cluster(job_id, params_json)


@app.function(
    image=pic_image,
    gpu="T4",
    memory=8192,
    timeout=3600,
    max_containers=1,
    retries=modal.Retries(max_retries=1, backoff_coefficient=2.0, initial_delay=10.0),
    secrets=[modal.Secret.from_name("pic-env")],
)
async def run_pipeline(job_id: str, params_json: str | None = None) -> None:
    """Full pipeline: discover images in R2, deduplicate, ingest, then cluster."""
    from pic.worker.pipeline import run_pipeline as _run_pipeline

    await _run_pipeline(job_id, params_json)


@app.function(
    image=pic_check_image,
    schedule=modal.Cron("*/15 * * * *"),
    timeout=120,
    max_containers=1,
    retries=modal.Retries(max_retries=2, backoff_coefficient=2.0, initial_delay=5.0),
    secrets=[modal.Secret.from_name("pic-env")],
)
async def check_gdrive_for_new_files() -> None:
    """Tier 1 (CPU): Lightweight cron — check GDrive folder, spawn GPU worker if files found."""
    await _check_gdrive_for_new_files_impl()


@app.function(
    image=pic_image,
    gpu="T4",
    memory=8192,
    timeout=3600,
    max_containers=1,
    retries=modal.Retries(max_retries=2, backoff_coefficient=2.0, initial_delay=10.0),
    secrets=[modal.Secret.from_name("pic-env")],
)
async def sync_gdrive_to_r2(job_id: str | None = None, params_json: str | None = None) -> None:
    """Tier 2 (GPU): Download from GDrive, process, upload to R2, cluster."""
    from pic.config import settings

    if not settings.gdrive_folder_id or not settings.gdrive_service_account_json:
        return

    import uuid

    from pic.core.database import async_session
    from pic.models.db import Job, JobStatus, JobType

    if job_id is None:
        job_id = str(uuid.uuid4())
        async with async_session() as db:
            db.add(Job(id=job_id, type=JobType.GDRIVE_SYNC, status=JobStatus.PENDING))
            await db.commit()

    from pic.worker.gdrive_sync import run_gdrive_sync as _run

    await _run(job_id, params_json)
