# Self-Hosted Deployment

PIC runs without Modal or any cloud account. The default worker backend is
`local`: the API records jobs in Postgres and the `pic-worker` process picks
them up.

## Docker Compose

The README quick start is the full self-hosted setup:

```bash
mkdir -p data/images
docker compose up --build -d
cp /path/to/photos/*.jpg data/images/
curl -X POST http://localhost:8000/api/v1/pipeline/run
```

Services:

| Service | Image target | Role |
|---|---|---|
| `db` | `pgvector/pgvector:pg18` | Metadata and vectors |
| `api` | `Dockerfile` target `api` | Applies migrations on start, serves the API and `/files` |
| `worker` | `Dockerfile` target `worker` | `pic-worker`: runs cluster, pipeline, URL-ingest and GDrive-sync jobs |

Storage is the local backend, mounted from `./data` at `/data` in both containers.

## Running the worker outside Docker

```bash
uv sync --extra ml
PIC_DATABASE_URL=postgresql+asyncpg://pic:pic_local@localhost:5432/pic \
PIC_STORAGE_BACKEND=local PIC_LOCAL_STORAGE_PATH=./data \
uv run pic-worker
```

The worker polls every 2 seconds, runs one job at a time, finishes the current
job on SIGTERM, and on start marks any RUNNING local job left by a crashed
worker as FAILED. Run a single worker.

## GPU

The embedding code picks CUDA, then Apple MPS, then CPU.

- **macOS:** run the worker natively as above to use the Apple GPU. Docker on macOS is CPU only.
- **Linux with NVIDIA:** not supported yet. The lockfile pins CPU-only torch on Linux; see the "Local NVIDIA GPU support" item in `ROADMAP.md`.

## Google Drive sync

The 15-minute Drive check only exists on Modal. With the local backend, trigger
a sync with `POST /api/v1/gdrive/sync`.

## Exposing the API publicly

Compose binds the API to `127.0.0.1` and disables auth for local use. Before
putting it on a public address:

- Set `PIC_API_KEY` to a long random value and remove `PIC_AUTH_DISABLED`.
- Put a reverse proxy in front for TLS and rate limiting. PIC has no built-in
  rate limiter; the job endpoints are bounded only by the pending-job queue
  limit (HTTP 429 when full). For example, with Caddy and the
  [caddy-ratelimit](https://github.com/mholt/caddy-ratelimit) module, or nginx
  `limit_req`.
