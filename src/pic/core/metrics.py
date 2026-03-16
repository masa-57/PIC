"""Prometheus metrics helpers for PIC-specific background job counters."""

from prometheus_client import Counter

from pic.models.db import JobStatus, JobType

jobs_created_total = Counter(
    "jobs_created_total",
    "Total number of background jobs created",
    labelnames=["type"],
)

jobs_completed_total = Counter(
    "jobs_completed_total",
    "Total number of background jobs that reached a terminal status",
    labelnames=["type", "status"],
)


def _job_type_label(job_type: JobType | str) -> str:
    return job_type.name if isinstance(job_type, JobType) else str(job_type).upper()


def _job_status_label(status: JobStatus | str) -> str:
    return status.name if isinstance(status, JobStatus) else str(status).upper()


def record_job_created(job_type: JobType | str) -> None:
    """Increment the created-job counter."""
    jobs_created_total.labels(type=_job_type_label(job_type)).inc()


def record_job_finished(job_type: JobType | str, status: JobStatus | str) -> None:
    """Increment the terminal job counter."""
    jobs_completed_total.labels(
        type=_job_type_label(job_type),
        status=_job_status_label(status),
    ).inc()
