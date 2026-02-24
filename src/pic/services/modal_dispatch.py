"""Dispatch ML jobs to Modal functions (replaces AWS Batch)."""

import functools
import json
import logging

import modal

from pic.core.constants import default_retry

logger = logging.getLogger(__name__)

# Modal function names — keep in sync with modal_app.py
MODAL_APP_NAME = "nic"
MODAL_FN_INGEST = "run_ingest"
MODAL_FN_CLUSTER = "run_cluster"
MODAL_FN_PIPELINE = "run_pipeline"
MODAL_FN_GDRIVE_SYNC = "sync_gdrive_to_r2"

_retry = default_retry


@functools.lru_cache(maxsize=8)
def _get_modal_function(app_name: str, fn_name: str) -> modal.Function:  # type: ignore[type-arg]
    """Cache Modal Function.from_name lookups to avoid repeated API calls."""
    return modal.Function.from_name(app_name, fn_name)


def _spawn_modal_job(fn_name: str, *args: object) -> str:
    """Spawn a Modal function and return its call ID."""
    fn = _get_modal_function(MODAL_APP_NAME, fn_name)
    call = fn.spawn(*args)
    logger.info("Spawned Modal %s call_id=%s", fn_name, call.object_id)
    return call.object_id


@_retry
async def submit_ingest_job(image_id: str, s3_key: str) -> str:
    """Trigger Modal function to process an image. Returns the Modal call ID."""
    return _spawn_modal_job(MODAL_FN_INGEST, image_id)


@_retry
async def submit_cluster_job(job_id: str, params: dict[str, int] | None = None) -> str:
    """Trigger Modal function to run clustering. Returns the Modal call ID."""
    params_json = json.dumps(params) if params else None
    return _spawn_modal_job(MODAL_FN_CLUSTER, job_id, params_json)


@_retry
async def submit_pipeline_job(job_id: str, params: dict[str, int] | None = None) -> str:
    """Trigger Modal function to run full pipeline. Returns the Modal call ID."""
    params_json = json.dumps(params) if params else None
    return _spawn_modal_job(MODAL_FN_PIPELINE, job_id, params_json)


@_retry
async def submit_gdrive_sync_job(job_id: str, params: dict[str, int] | None = None) -> str:
    """Trigger Modal function to sync from Google Drive. Returns the Modal call ID."""
    params_json = json.dumps(params) if params else None
    return _spawn_modal_job(MODAL_FN_GDRIVE_SYNC, job_id, params_json)
