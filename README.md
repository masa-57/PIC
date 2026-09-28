# PIC: Product Image Clustering

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

PIC organizes a folder of product photos into groups, so you can turn thousands of loose images into a clean product catalog. It is open source and self-hosted: one `docker compose up`, no cloud accounts.

It clusters at two levels:

- **Level 1 (L1): same product.** Photos of one item from different angles, crops or zoom levels become one group.
- **Level 2 (L2): similar products.** L1 groups that share a design, style or category are collected into clusters.

Clusters are suggestions and are rebuilt on every run. **Products** are yours: you build them from the suggestions in the web UI (merge groups, split, prune), and re-clustering never changes them.

## Quick start

You need Docker and nothing else.

```bash
git clone https://github.com/masa-57/PIC.git
cd PIC
mkdir -p data/images
docker compose up --build -d
```

Open **http://localhost:8000/ui**, then:

1. On **Runs**, keep **Local folder** selected, click **Choose folder…** and pick any folder of product photos (subfolders are included).
2. Click **Upload and run pipeline**. The run shows its step, progress and a time estimate.
3. Open **Clusters** to browse the result. Click a thumbnail to enlarge it.

The first run downloads the DINOv2 model (about 350 MB); later runs reuse it. API docs are at http://localhost:8000/docs.

Compose starts three services: Postgres with pgvector, the API (which applies database migrations on start) and `pic-worker`, which runs the jobs. Images and thumbnails are stored in `./data`.

On Linux, if the worker cannot write to `data/`, run `sudo chown -R 1001 data` (the containers run as uid 1001).

## Using the web UI

**Runs** is where images come in and jobs are started:

| Source | What it does |
|---|---|
| Local folder | Uploads a folder from your computer through the browser, then runs the pipeline |
| Already in storage | Runs the pipeline on files you placed in the storage inbox yourself (`./data/images/` with Compose) |
| Google Drive | Syncs new images from a shared Drive folder (needs [Drive setup](docs/gdrive-setup-guide.md)) |
| URLs | Downloads public image URLs, then runs the pipeline |

**Re-cluster** rebuilds the clusters without adding images. Recent runs show progress, how long each run took, and errors.

**Clusters** lists L2 clusters as thumbnail cards, plus an **Unclustered** card for groups that did not fit any cluster. A cluster page shows its L1 groups.

**Products** are your curated catalog:

- On a cluster page, select groups or single images and click **Make product**. Selecting several groups merges them; selecting some images of a group splits them off. **Add to product** adds the selection to an existing product.
- On a product page, remove images, **split** some into a new product, **merge** into another product, or edit the title, description and tags.
- Groups whose images already belong to a product show **✓ product**, so after the next run you only need to look at new groups.

When `PIC_API_KEY` is set, the UI asks for it once and keeps a 30-day session cookie.

## How it works

<p align="center">
  <img src="docs/images/architecture.svg" alt="PIC architecture" width="900"/>
</p>

A **pipeline run**:

1. **Discovers** new files in the storage inbox (`images/`) and skips exact duplicates by SHA-256 content hash (they move to `rejected/`).
2. **Ingests** each image: DINOv2 embedding, perceptual hashes, dimensions and a thumbnail. Ingested files move to `processed/`.
3. **Clusters** everything:
   - L1: HDBSCAN on DINOv2 cosine distance groups near-duplicates.
   - L2: UMAP reduces the L1 groups' representative embeddings, then HDBSCAN groups them.

Jobs are rows in Postgres. The API creates them and a worker runs them one at a time: `pic-worker` by default, or [Modal](docs/deployment/modal-setup.md) serverless GPU functions if you set `PIC_WORKER_BACKEND=modal`. Only one pipeline or clustering job runs at a time.

**Components**

| Component | Role |
|---|---|
| FastAPI app | JSON API under `/api/v1` and the web UI under `/ui` (Jinja2 + htmx, no build step) |
| `pic-worker` or Modal | Embeddings (DINOv2) and clustering (HDBSCAN, UMAP) |
| PostgreSQL + pgvector | Images, groups, clusters, products, jobs, and embeddings with an HNSW index for similarity search |
| Object storage | Local filesystem, S3-compatible (AWS S3, Cloudflare R2, MinIO) or Google Cloud Storage |

## Faster runs on a Mac

Docker on macOS cannot use the Apple GPU. For large folders, run the database and API in Docker and the worker natively:

```bash
docker compose up -d db api      # not plain "up": that would also start the Docker worker
uv sync --extra ml
PIC_DATABASE_URL='postgresql+asyncpg://pic:pic_local@localhost:5432/pic?sslmode=disable' \
PIC_STORAGE_BACKEND=local PIC_LOCAL_STORAGE_PATH=./data \
uv run pic-worker
```

The worker picks Apple's MPS device automatically. The first run after the worker starts loads the model (a few seconds); later runs skip that. The GPU matters most for large batches, where embedding dominates the run time.

## API

Everything the UI does is also in the JSON API under `/api/v1`. Interactive docs: `/docs`.

Requests need an `X-API-Key` header when `PIC_API_KEY` is set. For local use, `PIC_AUTH_DISABLED=true` turns auth off explicitly (Compose does this). With neither set, the API returns 503, so a misconfigured server never runs open by accident.

```bash
# Upload images to the inbox, then run the pipeline
curl -F files=@mug-front.jpg -F files=@mug-side.jpg http://localhost:8000/api/v1/images/upload
curl -X POST http://localhost:8000/api/v1/pipeline/run

# Follow the job
curl http://localhost:8000/api/v1/jobs
```

| Endpoints | Purpose |
|---|---|
| `/images` | List and inspect images, upload files, ingest from URLs |
| `/pipeline/run` | Discover, deduplicate, ingest and cluster in one job |
| `/clusters` | Run clustering; list L1 groups and L2 clusters |
| `/products` | Product CRUD; create from `l1_group_ids`; add/remove images; split; merge; list uncurated groups (`/candidates`) |
| `/search` | Similar images (vector search) and near-duplicates (pHash) |
| `/jobs` | Job status and results |
| `/gdrive/sync` | Start a Google Drive sync |

URL ingest only accepts public `http(s)` URLs. Localhost, private-network and link-local targets are rejected, including through redirects.

Health checks are `GET /health` and `GET /health/detailed`. Prometheus metrics are at `GET /metrics` (same auth as the API).

## Deploying

The Compose setup is meant for one machine and binds to `127.0.0.1`. Its settings live in the `x-pic-env` block of `docker-compose.yml` (Compose does not load a `.env` file into the containers). To run PIC on a server:

- Set `PIC_API_KEY` to a long random value and remove `PIC_AUTH_DISABLED`. The same key protects the API and the web UI.
- Put a reverse proxy in front for TLS and rate limiting. PIC has no built-in rate limiter.
- Choose storage. With the local backend, `/files` serves the stored images **without authentication**, and `PIC_ENV=production` refuses to start; use S3/R2/MinIO or GCS for a public deployment.
- Use any PostgreSQL with the pgvector extension (self-hosted, Neon, Supabase). Run `uv run alembic upgrade head` before starting a new version; Compose does this on API start, the plain `api` image does not.

The `Dockerfile` builds two images: `api` (slim, the default target) and `worker` (with the ML stack). See [self-hosting](docs/deployment/self-hosted.md), [architecture and settings](docs/deployment/architecture.md) and [Modal](docs/deployment/modal-setup.md).

## Configuration

All settings are `PIC_*` environment variables (see [`.env.example`](.env.example) and `src/pic/config.py`). The ones you are most likely to set:

| Variable | Purpose |
|---|---|
| `PIC_DATABASE_URL` | PostgreSQL URL (`postgresql+asyncpg://…`) |
| `PIC_API_KEY` / `PIC_AUTH_DISABLED` | Protect the API and UI, or explicitly run open |
| `PIC_STORAGE_BACKEND` | `local`, `s3` or `gcs` (Compose uses `local`) |
| `PIC_LOCAL_STORAGE_PATH` | Root folder for the local backend |
| `PIC_S3_BUCKET`, `PIC_S3_ENDPOINT_URL`, `PIC_S3_ACCESS_KEY_ID`, `PIC_S3_SECRET_ACCESS_KEY` | S3-compatible storage |
| `PIC_GCS_BUCKET`, `PIC_GCS_PROJECT_ID`, `PIC_GCS_CREDENTIALS_JSON` | Google Cloud Storage |
| `PIC_WORKER_BACKEND` | `local` (`pic-worker`, default) or `modal` |
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON`, `PIC_GDRIVE_FOLDER_ID` | Google Drive sync |
| `PIC_MAX_UPLOAD_SIZE_MB` | Largest request and uploaded file (default 20) |
| `PIC_L1_*`, `PIC_L2_*` | Clustering parameters (defaults suit most catalogs) |

## Development

```bash
uv sync --extra ml                                  # dependencies, including the ML stack
docker compose up -d db                             # Postgres for the API and integration tests
uv run fastapi dev src/pic/main.py                  # API with reload
uv run pic-worker                                   # worker (needs the storage settings above)

uv run ruff check src/ tests/ scripts/              # lint
uv run ruff format src/ tests/ scripts/             # format
uv run mypy src/pic/                                # type check (strict)
uv run pytest -m unit                               # fast tests, no services
uv run pytest -m integration                        # needs Postgres; see below
uv run pip-audit --skip-editable                    # dependency audit
```

Integration tests truncate every table in the database they use. Point them at a throwaway database, not your catalog:

```bash
docker compose exec db psql -U pic -d pic -c "CREATE DATABASE pic_test"
PIC_DATABASE_URL='postgresql+asyncpg://pic:pic_local@localhost:5432/pic_test?sslmode=disable' uv run pytest -m integration
```

The `Makefile` has shortcuts (`make help`). Guidance for AI coding assistants is in [AGENTS.md](AGENTS.md).

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md), and the [roadmap](ROADMAP.md) for what is planned. Please report security issues as described in [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
