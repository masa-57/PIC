# Migration Plan: AWS → Railway + Modal + Cloudflare R2

**Date**: 2026-02-10
**Status**: Phases 1–4 complete, E2E verified
**Goal**: Replace AWS infrastructure (ECS, Batch, Lambda, S3, CDK) with Railway (API), Modal (GPU ML), and Cloudflare R2 (storage) to reduce operational complexity.

## Branching Strategy

All migration work happens on a `migrate/railway-modal` branch. The `main` branch stays untouched and deployed on AWS throughout the migration. This provides a clean rollback — if the new stack doesn't work, `main` is still fully functional.

**Workflow:**
- Create `migrate/railway-modal` from `main`
- All migration phases are committed to this branch
- Test each phase on the new stack before proceeding
- Once the full pipeline is verified end-to-end, merge to `main`
- Decommission AWS infrastructure after merge

**During migration, both stacks coexist:**
- AWS (main branch): ECS API + Batch workers + S3
- New stack (branch): Railway API + Modal workers + R2
- Neon database is shared (external to both)

## Motivation

The current AWS stack uses ~12 services and ~540 lines of CDK to run what is fundamentally a FastAPI app, a background ML worker, object storage, and Postgres. Platform friction (GPU quotas, spot pricing, Batch versioning, Lambda bundling, IAM policies) has consumed significant development time. The new stack eliminates all infrastructure-as-code in favor of platform-managed deployment.

## Target Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Railway     │────▶│  Neon        │◀────│  Modal           │
│  (FastAPI)   │     │  (PostgreSQL │     │  (GPU workers)   │
│              │     │   + pgvector)│     │                  │
└──────┬───────┘     └──────────────┘     └────────▲─────────┘
       │                                           │
       │         ┌──────────────────┐              │
       └────────▶│  Cloudflare R2   │──────────────┘
                 │  (image storage) │
                 └──────────────────┘
```

- **Railway**: Hosts FastAPI API. Deploys on `git push`. Managed HTTPS, auto-scaling.
- **Modal**: Runs DINOv2 embedding + UMAP/HDBSCAN clustering on GPU (T4). Serverless — no idle cost.
- **Cloudflare R2**: S3-compatible object storage. No egress fees.
- **Neon**: Stays as-is (already external to AWS).

## What Stays Untouched

These files have zero AWS dependencies and need no changes:

- `src/nic/api/*` — FastAPI endpoints
- `src/nic/services/clustering.py` — HDBSCAN, UMAP (pure Python)
- `src/nic/services/embedding.py` — DINOv2, imagehash (pure Python)
- `src/nic/services/vector_store.py` — SQLAlchemy/pgvector
- `src/nic/models/*` — SQLAlchemy models, Pydantic schemas
- `src/nic/core/*` — async database engine, logging
- `tests/*` — all 30 unit tests

## Migration Steps

### Phase 1: Cloudflare R2 (Storage)

**Goal**: Replace AWS S3 with R2. Minimal code changes since R2 is S3-compatible.

#### Step 1.1: Create R2 bucket
- Create a Cloudflare account and R2 bucket named `nic-images`
- Generate R2 API token with read/write permissions
- Note the S3-compatible endpoint: `https://<account-id>.r2.cloudflarestorage.com`

#### Step 1.2: Update image_store.py
Replace the boto3 S3 client to point at R2:

```python
# src/nic/services/image_store.py
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,  # R2 endpoint
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name="auto",
    )
```

#### Step 1.3: Update config.py
```python
# Remove:
batch_job_queue: str = "nic-job-queue"
batch_job_definition: str = "nic-worker"

# Add:
s3_endpoint_url: str = ""       # R2 S3-compat endpoint
s3_access_key_id: str = ""      # R2 API token
s3_secret_access_key: str = ""  # R2 API secret
```

#### Step 1.4: Migrate existing images
- Copy objects from AWS S3 to R2 using `rclone` or `aws s3 sync` + `rclone copy`
- Verify object count matches

**Files changed**: `image_store.py`, `config.py`, `.env.example`
**Lines changed**: ~15

---

### Phase 2: Modal (GPU Workers)

**Goal**: Replace AWS Batch + Lambda with Modal functions for ingest and clustering.

#### Step 2.1: Create Modal app definition
New file `src/nic/modal_app.py`:

```python
import modal

app = modal.App("nic")

# Container image with ML dependencies
nic_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_pyproject("pyproject.toml", extra="ml")
)

@app.function(
    image=nic_image,
    gpu="T4",
    timeout=1800,
    secrets=[modal.Secret.from_name("nic-secrets")],
)
async def run_ingest(image_id: str):
    """Process an uploaded image: compute pHash + DINOv2 embedding."""
    from nic.worker.ingest import run_ingest as _run_ingest
    await _run_ingest(image_id)

@app.function(
    image=nic_image,
    gpu="T4",
    timeout=1800,
    secrets=[modal.Secret.from_name("nic-secrets")],
)
async def run_cluster(job_id: str, params_json: str | None = None):
    """Run L1 + L2 clustering pipeline."""
    from nic.worker.cluster import run_cluster as _run_cluster
    await _run_cluster(job_id, params_json)
```

#### Step 2.2: Create Modal secret
```bash
modal secret create nic-secrets \
  NIC_DATABASE_URL=<neon-url> \
  NIC_S3_BUCKET=nic-images \
  NIC_S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com \
  NIC_S3_ACCESS_KEY_ID=<r2-key> \
  NIC_S3_SECRET_ACCESS_KEY=<r2-secret>
```

#### Step 2.3: Rewrite batch.py → modal_dispatch.py
Replace AWS Batch `submit_job` calls with Modal function triggers:

```python
# src/nic/services/modal_dispatch.py
import modal

async def submit_ingest_job(image_id: str) -> str:
    """Trigger Modal function to process an image."""
    fn = modal.Function.from_name("nic", "run_ingest")
    call = fn.spawn(image_id)
    return call.object_id

async def submit_cluster_job(job_id: str, params: dict | None = None) -> str:
    """Trigger Modal function to run clustering."""
    fn = modal.Function.from_name("nic", "run_cluster")
    params_json = json.dumps(params) if params else None
    call = fn.spawn(job_id, params_json)
    return call.object_id
```

#### Step 2.4: Update API imports
All files that import from `nic.services.batch` should import from `nic.services.modal_dispatch` instead. Same interface (`submit_ingest_job`, `submit_cluster_job`), just a different backend.

Search for all imports:
- `src/nic/api/jobs.py` (cluster endpoint)
- `scripts/seed.py` (bulk upload script)
- Any other callers

#### Step 2.5: Update seed.py
Replace Batch job polling with Modal call tracking. Modal provides `.get()` to wait for completion, simplifying the poll loop.

#### Step 2.6: Simplify worker entrypoint
`src/nic/worker/entrypoint.py` (the argparse CLI) can be kept for local dev/testing but is no longer the production entry point. Modal calls `ingest.run_ingest()` and `cluster.run_cluster()` directly.

**Files created**: `modal_app.py`, `modal_dispatch.py`
**Files deleted**: `batch.py`
**Files changed**: API imports, `seed.py`
**Lines changed**: ~150

---

### Phase 3: Railway (API Hosting)

**Goal**: Replace ECS Fargate + ALB with Railway. Zero infrastructure code.

#### Step 3.1: Create Railway project
- Connect GitHub repo to Railway
- Railway auto-detects the Dockerfile and builds the `api` target

#### Step 3.2: Add railway.json (optional, for explicit config)
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "dockerfilePath": "Dockerfile",
    "dockerTarget": "api"
  },
  "deploy": {
    "healthcheckPath": "/health",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

#### Step 3.3: Configure environment variables in Railway dashboard
```
NIC_DATABASE_URL=<neon-url>
NIC_S3_BUCKET=nic-images
NIC_S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
NIC_S3_ACCESS_KEY_ID=<r2-key>
NIC_S3_SECRET_ACCESS_KEY=<r2-secret>
```

#### Step 3.4: Set up custom domain (optional)
Railway provides a `*.up.railway.app` domain by default. Custom domain can be added later.

**Files created**: `railway.json` (optional)
**Files changed**: none (Dockerfile already has `api` target)

---

### Phase 4: Ingestion Trigger

**Goal**: Replace S3 event → Lambda → Batch with a simpler trigger.

#### Option A: seed.py calls Modal directly (recommended for now)
Since `seed.py` is the only upload path, it already knows which images were uploaded. After uploading to R2, call `modal_dispatch.submit_ingest_job()` directly. No event trigger needed.

This is already handled by Phase 2 changes to `seed.py`.

#### Option B: R2 event notification → Modal webhook (future)
If other upload paths are added later:
1. Add a `@modal.web_endpoint` to `modal_app.py` that accepts R2 event notification payloads
2. Configure R2 bucket event notification to POST to the Modal webhook URL
3. The webhook creates the DB record and spawns `run_ingest`

**Recommendation**: Start with Option A. Add Option B only if needed.

---

### Phase 5: CI/CD Simplification

**Goal**: Replace the 198-line GitHub Actions workflow with a simpler pipeline.

#### Step 5.1: New `.github/workflows/ci-cd.yml`
```yaml
name: CI/CD
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen
      - run: uv run ruff check src/ tests/ scripts/
      - run: uv run ruff format --check src/ tests/ scripts/
      - run: uv run pytest -m unit

  deploy-modal:
    needs: lint-and-test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: modal-com/modal-setup@v2
      - run: modal deploy src/nic/modal_app.py

  # Railway deploys automatically from GitHub — no step needed
```

#### Step 5.2: Delete ECR, ECS, CDK deploy steps
All Docker build + push + ECS force-deploy logic is removed. Railway builds and deploys automatically on push to main.

**Files changed**: `.github/workflows/ci-cd.yml`
**Lines**: 198 → ~35

---

### Phase 6: Cleanup

**Goal**: Remove all AWS-specific code and infrastructure.

#### Step 6.1: Delete infrastructure code
```
rm -rf infra/                          # All CDK stacks (~540 LOC)
```

#### Step 6.2: Delete Lambda handler
```
rm -rf infra/lambda/                   # Already removed with infra/
```

#### Step 6.3: Delete old batch service
```
rm src/nic/services/batch.py           # Replaced by modal_dispatch.py
```

#### Step 6.4: Remove worker Dockerfile target
Edit `Dockerfile` to remove the `worker` stage — Modal builds its own container. Keep the `api` target for Railway.

#### Step 6.5: Clean up dependencies
```bash
# Remove AWS-specific deps that are no longer needed at API level
# boto3 is still needed for R2 (S3-compatible), so it stays
# aws-cdk-lib, constructs — remove from dev deps
uv remove aws-cdk-lib constructs
```

#### Step 6.6: Update CLAUDE.md
Remove all AWS-specific gotchas, update architecture diagram, update commands section.

#### Step 6.7: Update .env.example
Remove `NIC_BATCH_JOB_QUEUE`, `NIC_BATCH_JOB_DEFINITION`. Add `NIC_S3_ENDPOINT_URL`, `NIC_S3_ACCESS_KEY_ID`, `NIC_S3_SECRET_ACCESS_KEY`.

---

## Migration Order & Dependencies

```
Phase 1 (R2)  ──▶  Phase 2 (Modal)  ──▶  Phase 3 (Railway)  ──▶  Phase 5 (CI/CD)
                                                                        │
                        Phase 4 (Trigger) ◀─ part of Phase 2            ▼
                                                                  Phase 6 (Cleanup)
```

- Phase 1 must go first (workers need R2 access)
- Phase 2 depends on Phase 1 (Modal workers read from R2)
- Phase 3 is independent of Phase 2 (API doesn't need Modal to serve requests)
- Phase 5 depends on Phase 2 + 3 (CI/CD deploys both)
- Phase 6 is last (only after everything works on new stack)

## Rollback Strategy

Keep AWS infrastructure running during migration. Both stacks can coexist because:
- Neon database is external to both
- R2 and S3 are separate buckets (no conflict)
- Railway and ECS serve on different URLs

Cutover: point DNS/clients to Railway URL. If issues arise, revert to ECS URL.

## Cost Comparison (Estimated Monthly)

| Component | AWS (Current) | New Stack |
|-----------|--------------|-----------|
| API hosting | ECS Fargate ~$15 + ALB ~$16 + NAT ~$32 = **~$63** | Railway ~$5 (Hobby) or ~$20 (Pro) |
| ML compute | Batch spot ~$5-15 (bursty) | Modal ~$5-10 (pay per second GPU) |
| Storage | S3 ~$1 | R2 ~$0 (10GB free, no egress) |
| Database | Neon ~$0 (free tier) | Neon ~$0 (unchanged) |
| Lambda | ~$0 | N/A (eliminated) |
| **Total** | **~$70-90/mo** | **~$10-30/mo** |

Note: AWS cost dominated by NAT Gateway ($32/mo) and ALB ($16/mo) — fixed costs regardless of traffic.

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Modal cold start latency | Medium | First invocation ~30-60s (container pull). Acceptable for batch processing. |
| R2 S3 compatibility gaps | Low | R2 supports all operations used (get, put, copy, delete, presigned URLs). |
| Railway build issues | Low | Uses same Dockerfile `api` target already tested. |
| Modal GPU availability | Low | Modal manages GPU fleet; no quota requests needed. |
| Neon connection limits | Low | Same as current — unchanged. |

## Verification Checklist

- [x] R2 bucket created, seed.py can upload images
- [x] Modal functions deploy and can compute embeddings
- [x] Modal functions can read from R2 and write to Neon
- [x] Railway deploys API from GitHub push
- [x] API on Railway can query Neon and generate R2 presigned URLs
- [x] `POST /api/v1/clusters/run` triggers Modal clustering
- [x] seed.py works end-to-end on new stack
- [x] All 30 unit tests still pass
- [x] CI/CD pipeline runs lint → test → modal deploy
- [x] Old AWS infrastructure can be decommissioned
