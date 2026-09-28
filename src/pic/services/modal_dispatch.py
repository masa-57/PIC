"""Modal worker backend: spawn the Modal function that runs a job."""

import functools
import json
import logging
from typing import Any

import modal

from pic.core.constants import default_retry
from pic.models.db import JobType

logger = logging.getLogger(__name__)

# Modal function names — keep in sync with modal_app.py
MODAL_APP_NAME = "pic"
MODAL_FN_CLUSTER = "run_cluster"
MODAL_FN_PIPELINE = "run_pipeline"
MODAL_FN_GDRIVE_SYNC = "sync_gdrive_to_r2"
MODAL_FN_URL_INGEST = "run_url_ingest"

# Job type -> Modal function name.
MODAL_FUNCTIONS: dict[JobType, str] = {
    JobType.CLUSTER_FULL: MODAL_FN_CLUSTER,
    JobType.PIPELINE: MODAL_FN_PIPELINE,
    JobType.GDRIVE_SYNC: MODAL_FN_GDRIVE_SYNC,
    JobType.URL_INGEST: MODAL_FN_URL_INGEST,
}

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
async def _spawn_with_retry(fn_name: str, job_id: str, params_json: str | None) -> str:
    return _spawn_modal_job(fn_name, job_id, params_json)


async def spawn_modal_job(job_type: JobType, job_id: str, params: dict[str, Any] | None) -> str:
    """Spawn the Modal function for ``job_type``. Returns the Modal call ID."""
    fn_name = MODAL_FUNCTIONS.get(job_type)
    if fn_name is None:
        raise ValueError(f"No Modal function for job type {job_type.value}")
    params_json = json.dumps(params) if params else None
    return await _spawn_with_retry(fn_name, job_id, params_json)
