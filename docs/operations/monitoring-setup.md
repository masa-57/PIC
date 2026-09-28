# Monitoring Setup

This document describes how to monitor PIC: the API with Prometheus and Grafana, background jobs through the database, and liveness through the health endpoints.

## Metrics Endpoint

The PIC API exposes `GET /metrics` via `prometheus-fastapi-instrumentator`.
This endpoint returns metrics in Prometheus text exposition format.

`/metrics` is not under `/api/v1`, but it is still protected by the same API-key dependency as the application. In practice:

- If `PIC_API_KEY` is set, scrapers must send `X-API-Key: <value>`
- If `PIC_API_KEY` is unset and `PIC_AUTH_DISABLED=false`, `/metrics` returns `503`
- If `PIC_AUTH_DISABLED=true`, `/metrics` is intentionally unauthenticated. Use that only for local development or an internal-only scrape target

To verify locally:

```bash
curl -H "X-API-Key: ${PIC_API_KEY}" http://localhost:8000/metrics
```

## Key Metrics

### HTTP Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | method, handler, status | Auto-instrumented request count |
| `http_request_duration_seconds` | Histogram | method, handler | Low-cardinality latency histogram by handler |
| `http_request_duration_highr_seconds` | Histogram | none | High-resolution latency histogram for global percentile alerts |
| `http_request_size_bytes` | Summary | handler | Observed request body sizes |
| `http_response_size_bytes` | Summary | handler | Observed response sizes |

### Job Metrics (limited, read this first)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `jobs_created_total` | Counter | type | Jobs created through the API (`CLUSTER_FULL`, `PIPELINE`, `URL_INGEST`, `GDRIVE_SYNC`) |
| `jobs_completed_total` | Counter | type, status | Jobs that reached `COMPLETED` or `FAILED`, **as seen by the API process only** |

Jobs run in `pic-worker` or on Modal, not in the API. Those processes count job outcomes in their own memory, and neither exposes a metrics endpoint, so those counts are never scraped. The API's `/metrics` only sees:

- `jobs_created_total` for jobs created through the API. Pipeline jobs queued by a URL ingest job are created in the worker and are missing.
- `jobs_completed_total{status="FAILED"}` for jobs the API itself marks failed: dispatch failures, stale `RUNNING` jobs swept by `/health/detailed`, and Modal failures detected by `/health/detailed`.

Successful jobs and most failures never appear there. Do not build success ratios or failure alerts on `jobs_completed_total`; they will look healthy while jobs fail. Use [Job Monitoring](#job-monitoring) instead.

### Database Pool Metrics

These describe the API process's SQLAlchemy pool (size `PIC_DB_POOL_SIZE`, default 10, plus up to `PIC_DB_POOL_MAX_OVERFLOW`, default 20).

| Metric | Type | Description |
|--------|------|-------------|
| `db_pool_checked_out` | Gauge | Connections currently checked out |
| `db_pool_checked_in` | Gauge | Connections available in pool |
| `db_pool_overflow` | Gauge | Overflow connections in use |

## Job Monitoring

Job state lives in the `jobs` table. Read it through the API or the database:

- **Web UI**: the **Runs** page lists recent jobs with status and progress.
- **API**: `GET /api/v1/jobs?status=failed` lists failed jobs, newest first, with their `error`. `GET /api/v1/jobs/{id}` returns one job.
- **`GET /health/detailed`** (needs `X-API-Key` when auth is on) returns `recent_failed_jobs` (jobs failed in the last hour), `stale_jobs_swept` and the pool status. Its `status` is `warning` when more than 5 jobs failed in the last hour, and `degraded` when the database is unreachable. Calling it also marks `RUNNING` jobs older than `PIC_STALE_JOB_TIMEOUT_MINUTES` (default 90) as failed.
- **SQL**, for a dashboard or an exporter such as `sql_exporter`:

  ```sql
  SELECT type, status, count(*)
  FROM jobs
  WHERE created_at > now() - interval '1 day'
  GROUP BY type, status;
  ```

  Enum values are stored UPPERCASE in the database (`FAILED`, `PIPELINE`, ...).

A simple setup: poll `/health/detailed` every few minutes from an uptime checker and alert when `status` is not `ok`.

## Health Endpoints

- `GET /health` needs no auth. It always returns HTTP 200; the body says `"status": "ok"` or `"degraded"` (database unreachable). Check the body, not just the status code.
- `GET /health/detailed` is described above.

## Recommended Alerts

### Critical

- `http_request_duration_highr_seconds` p99 > 5s for 5 minutes
- `http_requests_total` with status 5xx rate > 1% of total for 5 minutes
- `db_pool_checked_out` equals pool size for 2 minutes (pool exhaustion)
- `/health` not answering, or its body not `"status": "ok"`, for 1 minute

### Warning

- `http_request_duration_highr_seconds` p95 > 2s for 10 minutes
- `/health/detailed` `status` is `warning` (more than 5 failed jobs in the last hour)
- `jobs` table has `PENDING` jobs older than 15 minutes (worker down or stuck)
- `db_pool_overflow` > 0 for 5 minutes (pool under pressure)

## Prometheus Scrape Configuration

Prometheus cannot scrape the default PIC endpoint anonymously. Use one of these patterns:

1. Scrape an internal-only PIC deployment where `PIC_AUTH_DISABLED=true` was set deliberately.
2. Scrape a reverse proxy or sidecar that injects the required `X-API-Key` header before forwarding to PIC.

Example scrape config for an internal-only target with explicit auth disable:

```yaml
scrape_configs:
  - job_name: "pic-api"
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["<PIC_API_HOST>:<PORT>"]
        labels:
          environment: "production"
```

If you keep `PIC_API_KEY` enabled, point Prometheus at a proxy endpoint that handles header injection. Do not assume a public ingress can scrape `/metrics` directly without credentials.

## Grafana Dashboard Configuration

### Setup

1. Add Prometheus as a data source in Grafana pointing to your Prometheus instance.
2. Import or create a dashboard with the panels described below.

### Recommended Panels

**Row: HTTP Overview**

- Request rate: `sum(rate(http_requests_total[5m]))`
- Error rate: `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))`
- Latency p50/p95/p99: `histogram_quantile(0.99, sum(rate(http_request_duration_highr_seconds_bucket[5m])) by (le))`
- Handler latency p95: `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (handler, le))`

**Row: Background Jobs**

- Jobs created rate: `sum(rate(jobs_created_total[5m])) by (type)`
- For job outcomes, use a Postgres data source with the SQL query from [Job Monitoring](#job-monitoring), not `jobs_completed_total` (see the note under Job Metrics).

**Row: Database Pool**

- Connections checked out: `db_pool_checked_out`
- Pool utilization: `db_pool_checked_out / (db_pool_checked_out + db_pool_checked_in)`
- Overflow connections: `db_pool_overflow`

### Example Grafana Dashboard JSON

A minimal dashboard can be created by importing the following panels via
Grafana's "Add panel" feature using the PromQL queries listed above. For
a full dashboard template, generate one from Grafana's explore view after
the metrics endpoint is connected and producing data.
