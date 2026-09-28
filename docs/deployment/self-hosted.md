# Self-Hosted Deployment

PIC runs without Modal or any cloud account. The default worker backend is
`local`: the API records jobs in Postgres and the `pic-worker` process picks
them up.

## Docker Compose

The README quick start is the full self-hosted setup:

```bash
mkdir -p data/images
docker compose up --build -d
open http://localhost:8000/ui
```

On the **Runs** page, upload a folder (**Local folder**), or copy files into
`./data/images/` and use **Already in storage**, then run the pipeline.

Services:

| Service | Image target | Role |
|---|---|---|
| `db` | `pgvector/pgvector:pg18` | Metadata, embeddings, jobs, products |
| `api` | `Dockerfile` target `api` | Applies migrations on start; serves the JSON API (`/api/v1`), the web UI (`/ui`) and stored files (`/files`) |
| `worker` | `Dockerfile` target `worker` | `pic-worker`: runs pipeline, cluster, URL-ingest and Google Drive sync jobs |

Storage is the local backend, mounted from `./data` at `/data` in the `api` and
`worker` containers.

### Changing settings

The containers get their settings from the `x-pic-env` block at the top of
`docker-compose.yml`. Compose does not load a `.env` file into them. Edit that
block (or add an `env_file:` entry to both services), then recreate the
containers with `docker compose up -d`. Settings shared by the API and worker,
such as storage and Google Drive, must reach both.

## Running the worker outside Docker

```bash
docker compose up -d db api      # not plain "up", which also starts the Docker worker
uv sync --extra ml
PIC_DATABASE_URL='postgresql+asyncpg://pic:pic_local@localhost:5432/pic?sslmode=disable' \
PIC_STORAGE_BACKEND=local PIC_LOCAL_STORAGE_PATH=./data \
uv run pic-worker
```

The worker polls every 2 seconds, runs one job at a time, finishes the current
job on SIGTERM, and on start marks any RUNNING local job left by a crashed
worker as FAILED. Run a single worker: two workers would compete for jobs.

The first job after the worker starts loads the ML libraries and the DINOv2
model, which takes a few seconds; later jobs reuse them.

## GPU

The embedding code picks CUDA, then Apple MPS, then CPU.

- **macOS:** run the worker natively as above to use the Apple GPU. Docker on macOS is CPU only.
- **Linux with NVIDIA:** not supported yet. The lockfile pins CPU-only torch on Linux; see the "Local NVIDIA GPU support" item in `ROADMAP.md`.

The GPU speeds up embedding, which dominates large runs. For a few dozen images,
startup and clustering take most of the time and CPU and GPU runs are close.

## Google Drive sync

Set `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` and `PIC_GDRIVE_FOLDER_ID` for both the
API and the worker (see [the setup guide](../gdrive-setup-guide.md)). With the
local backend there is no automatic check: click **Sync now** on the Runs page
(Google Drive tab) or call `POST /api/v1/gdrive/sync`. The 15-minute automatic
check exists only on Modal.

## Exposing PIC publicly

Compose binds the API to `127.0.0.1` and disables auth for local use. Before
putting PIC on a public address:

- Set `PIC_API_KEY` to a long random value and remove `PIC_AUTH_DISABLED`
  (in `x-pic-env`). The key protects both the JSON API (`X-API-Key` header) and
  the web UI, which asks for it once and keeps a 30-day session cookie.
- Put a reverse proxy in front for TLS and rate limiting. PIC has no built-in
  rate limiter; the job endpoints are bounded only by the pending-job queue
  limit (HTTP 429 when full). For example, use Caddy with the
  [caddy-ratelimit](https://github.com/mholt/caddy-ratelimit) module, or nginx
  `limit_req`.
- Make sure the proxy passes the original scheme (`X-Forwarded-Proto`) and that
  the API trusts it (`fastapi run --forwarded-allow-ips <proxy address>`), so
  the session cookie gets the `Secure` flag.
- Don't serve images from the local backend publicly: `/files` has no
  authentication, and `PIC_ENV=production` refuses to start with local storage.
  Use S3-compatible storage (AWS S3, Cloudflare R2, MinIO) or GCS with private
  buckets; the UI and API hand out short-lived presigned URLs.
- The UI and API share one origin, so no CORS setup is needed. To call the API
  from a browser app on another origin, add CORS headers at the reverse proxy.

## Backups

Curated products live in the database; images and thumbnails live in storage.
Back up both. See [database backup and restore](../operations/database-backup-restore.md).
