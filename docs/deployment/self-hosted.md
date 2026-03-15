# Self-Hosted Deployment

Running PIC without Modal. This is best-effort guidance -- full Modal decoupling is on the [roadmap](../../ROADMAP.md).

## Overview

PIC's GPU workers are defined as Modal functions in `src/pic/modal_app.py`, but the underlying logic lives in standard Python modules that can be called directly:

- `src/pic/worker/ingest.py` -- Image ingestion logic
- `src/pic/worker/cluster.py` -- Clustering logic
- `src/pic/worker/pipeline.py` -- Pipeline orchestration
- `src/pic/worker/gdrive_sync.py` -- Google Drive sync
- `src/pic/worker/url_ingest.py` -- URL-based image ingestion (download, deduplicate, store)

## Running Workers Directly

The worker modules can be imported and called as regular async Python functions. Each worker function accepts a `job_id` and `params_json` string:

```python
import asyncio
from pic.worker.ingest import run_ingest

asyncio.run(run_ingest(job_id=1, params_json='{}'))
```

Note: You'll need all PIC environment variables set and the ML dependencies installed (`uv sync --extra ml`).

## Docker Compose (Full Stack)

For a complete local deployment:

```bash
# Start database
docker compose up db -d

# Apply migrations
uv run alembic upgrade head

# Run API server
uv run fastapi run src/pic/main.py --host 0.0.0.0 --port 8000

# Run workers as needed (in separate terminals or via supervisor)
uv run python -c "
import asyncio
from pic.worker.cluster import run_cluster
asyncio.run(run_cluster(job_id=1, params_json='{}'))
"
```

## Background Processing

For production without Modal, consider:

1. **Cron + script**: Schedule worker runs via system cron
2. **Supervisor/systemd**: Run workers as managed background processes
3. **Celery/Dramatiq**: Add a task queue (requires code changes -- see ROADMAP.md)

## GPU Support

For GPU-accelerated embedding generation, ensure:
- NVIDIA drivers and CUDA toolkit installed
- PyTorch installed with CUDA support: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121`
- The `PIC_DEVICE` environment variable is set (defaults to auto-detect)

Workers will automatically use GPU if available via PyTorch's device detection.
