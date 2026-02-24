# Monitoring Setup

This document describes how to monitor the NIC API using Prometheus and Grafana.

## Metrics Endpoint

The NIC API exposes a `/metrics` endpoint via `prometheus-fastapi-instrumentator`.
This endpoint returns metrics in Prometheus text exposition format.

To verify locally:

```bash
curl http://localhost:8000/metrics
```

## Key Metrics

### HTTP Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | method, endpoint, status | Total HTTP requests processed |
| `http_request_duration_seconds` | Histogram | method, endpoint | Request latency distribution |
| `http_requests_total` (instrumentator) | Counter | method, handler, status | Auto-instrumented request count |
| `http_request_duration_seconds` (instrumentator) | Histogram | method, handler | Auto-instrumented latency |

### Job Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `jobs_created_total` | Counter | type | Background jobs created (INGEST, CLUSTER_FULL, PIPELINE, etc.) |
| `jobs_completed_total` | Counter | type, status | Background jobs completed (COMPLETED, FAILED) |

### Database Pool Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `db_pool_checked_out` | Gauge | Connections currently checked out |
| `db_pool_checked_in` | Gauge | Connections available in pool |
| `db_pool_overflow` | Gauge | Overflow connections in use |

## Recommended Alerts

### Critical

- `http_request_duration_seconds` p99 > 5s for 5 minutes
- `http_requests_total` with status 5xx rate > 1% of total for 5 minutes
- `db_pool_checked_out` equals pool size for 2 minutes (pool exhaustion)
- `/health` endpoint returning non-200 for 1 minute

### Warning

- `http_request_duration_seconds` p95 > 2s for 10 minutes
- `jobs_completed_total{status="FAILED"}` rate increasing for 15 minutes
- `db_pool_overflow` > 0 for 5 minutes (pool under pressure)

## Prometheus Scrape Configuration

Add the following to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "nic-api"
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["<NIC_API_HOST>:<PORT>"]
        labels:
          environment: "production"
```

For Railway deployments, you may need to use a service discovery mechanism
or configure an external Prometheus instance to reach the Railway public URL.

## Grafana Dashboard Configuration

### Setup

1. Add Prometheus as a data source in Grafana pointing to your Prometheus instance.
2. Import or create a dashboard with the panels described below.

### Recommended Panels

**Row: HTTP Overview**

- Request rate: `rate(http_requests_total[5m])`
- Error rate: `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])`
- Latency p50/p95/p99: `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))`

**Row: Background Jobs**

- Jobs created rate: `rate(jobs_created_total[5m])` by type
- Jobs failed rate: `rate(jobs_completed_total{status="FAILED"}[5m])` by type
- Job success ratio: `rate(jobs_completed_total{status="COMPLETED"}[5m]) / rate(jobs_completed_total[5m])`

**Row: Database Pool**

- Connections checked out: `db_pool_checked_out`
- Pool utilization: `db_pool_checked_out / (db_pool_checked_out + db_pool_checked_in)`
- Overflow connections: `db_pool_overflow`

### Example Grafana Dashboard JSON

A minimal dashboard can be created by importing the following panels via
Grafana's "Add panel" feature using the PromQL queries listed above. For
a full dashboard template, generate one from Grafana's explore view after
the metrics endpoint is connected and producing data.
