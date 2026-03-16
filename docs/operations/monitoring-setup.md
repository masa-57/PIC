# Monitoring Setup

This document describes how to monitor the PIC API using Prometheus and Grafana.

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

### Job Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `jobs_created_total` | Counter | type | PIC custom counter for created background jobs (`CLUSTER_FULL`, `PIPELINE`, `URL_INGEST`, `GDRIVE_SYNC`) |
| `jobs_completed_total` | Counter | type, status | PIC custom counter for terminal job outcomes (`COMPLETED`, `FAILED`) |

### Database Pool Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `db_pool_checked_out` | Gauge | Connections currently checked out |
| `db_pool_checked_in` | Gauge | Connections available in pool |
| `db_pool_overflow` | Gauge | Overflow connections in use |

## Recommended Alerts

### Critical

- `http_request_duration_highr_seconds` p99 > 5s for 5 minutes
- `http_requests_total` with status 5xx rate > 1% of total for 5 minutes
- `db_pool_checked_out` equals pool size for 2 minutes (pool exhaustion)
- `/health` endpoint returning non-200 for 1 minute

### Warning

- `http_request_duration_highr_seconds` p95 > 2s for 10 minutes
- `jobs_completed_total{status="FAILED"}` rate increasing for 15 minutes
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

If you keep `PIC_API_KEY` enabled, point Prometheus at a proxy endpoint that handles header injection. Do not assume Railway or another public ingress can scrape `/metrics` directly without credentials.

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
- Jobs failed rate: `sum(rate(jobs_completed_total{status="FAILED"}[5m])) by (type)`
- Job success ratio: `sum(rate(jobs_completed_total{status="COMPLETED"}[5m])) by (type) / sum(rate(jobs_completed_total[5m])) by (type)`

**Row: Database Pool**

- Connections checked out: `db_pool_checked_out`
- Pool utilization: `db_pool_checked_out / (db_pool_checked_out + db_pool_checked_in)`
- Overflow connections: `db_pool_overflow`

### Example Grafana Dashboard JSON

A minimal dashboard can be created by importing the following panels via
Grafana's "Add panel" feature using the PromQL queries listed above. For
a full dashboard template, generate one from Grafana's explore view after
the metrics endpoint is connected and producing data.
