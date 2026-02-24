# Railway Resource Configuration

## Recommended Dashboard Settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| Memory | 512 MB | API-only (no ML deps in Railway image) |
| CPU | 0.5 vCPU | Sufficient for async FastAPI serving |
| Replicas | 1 | Advisory locks assume single instance |
| Region | Same as Neon DB | Minimize database latency |

## railway.json Configuration

The following are configured in `railway.json`:

- **Dockerfile**: `Dockerfile.railway` (API-only, no ML dependencies)
- **Health check**: `GET /health` with 30s timeout
- **Restart policy**: `ON_FAILURE` with max 3 retries

## Scaling Notes

- Do **not** scale to multiple replicas without removing/adapting the PostgreSQL
  advisory lock (`0x4E494301`) used by pipeline/cluster/gdrive workers.
- Modal handles all GPU compute — Railway only serves the API.
- The 512 MB memory limit is sufficient for the FastAPI process. Monitor via
  Railway metrics dashboard if request volume increases significantly.
