"""Prometheus metrics for the PIC API.

Defines application-level counters and histograms for HTTP request
tracking and background job monitoring. These complement the
auto-instrumentation provided by prometheus-fastapi-instrumentator
and the database pool gauges in ``nic.core.database``.
"""

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# HTTP request metrics
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests processed",
    labelnames=["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=["method", "endpoint"],
)

# ---------------------------------------------------------------------------
# Background job metrics
# ---------------------------------------------------------------------------

jobs_created_total = Counter(
    "jobs_created_total",
    "Total number of background jobs created",
    labelnames=["type"],
)

jobs_completed_total = Counter(
    "jobs_completed_total",
    "Total number of background jobs completed",
    labelnames=["type", "status"],
)
