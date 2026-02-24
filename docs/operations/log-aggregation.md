# Log Aggregation

This document describes the NIC project's logging configuration, Railway's built-in
log viewer, and recommended external log aggregation services.

## Current Logging Configuration

NIC uses Python's standard `logging` module with a custom `JSONFormatter`
(defined in `src/nic/core/logging.py`). In production, all log output is
structured JSON written to stdout.

### Log Format

Each log entry is a JSON object with the following fields:

```json
{
  "timestamp": "2025-01-15T10:30:00.123456+00:00",
  "level": "INFO",
  "logger": "nic.api.routes.images",
  "message": "Image ingested successfully",
  "request_id": "abc-123-def"
}
```

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 UTC timestamp |
| `level` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `logger` | Python logger name (module path) |
| `message` | Human-readable log message |
| `request_id` | X-Request-ID header value (when present) |
| `exception` | Full traceback string (when an exception is logged) |

### Configuration

The log level is controlled by the `NIC_LOG_LEVEL` environment variable
(default: `INFO`). The `setup_logging()` function in `src/nic/core/logging.py`
configures the root logger and quiets noisy libraries (`httpcore`, `httpx`,
`transformers`).

## Railway Built-in Log Viewer

Railway provides a built-in log viewer accessible from the service dashboard
under the **Logs** tab.

### Capabilities

- Real-time log streaming from running deployments.
- Basic text search within the current log buffer.
- Deployment-scoped log views.

### Limitations

- Logs are ephemeral and not persisted beyond the deployment lifecycle.
- Limited search functionality (no regex, no field-based queries).
- No alerting or metric extraction from logs.
- No log export or API access for programmatic consumption.
- Log retention is short (typically hours, not days).

For production use, an external log aggregation service is recommended.

## Recommended External Services

### Datadog

- Full-text search with field-based filtering.
- Log-to-metric conversion for alerting.
- APM integration for distributed tracing.
- Setup: Configure a Datadog log drain in Railway or use the Datadog agent.

### Grafana Loki

- Horizontally scalable log aggregation.
- Label-based indexing (efficient for structured JSON logs).
- Native integration with Grafana dashboards.
- Cost-effective for high-volume logging.
- Setup: Use Promtail or a syslog drain to forward logs.

### Papertrail

- Simple setup with syslog-based forwarding.
- Real-time tail and search.
- Alert rules on log patterns.
- Good for smaller deployments.
- Setup: Configure a syslog drain in Railway.

## Configuring Log Forwarding from Railway

Railway supports log drains that forward application logs to external services.

### Setup Steps

1. Open the Railway dashboard and navigate to the NIC project settings.
2. Go to **Settings** > **Log Drains** (or configure at the service level).
3. Add a new log drain with the destination URL provided by your log service:
   - **Datadog**: Use the Datadog HTTP log intake endpoint with your API key.
   - **Grafana Loki**: Use the Loki push API endpoint.
   - **Papertrail**: Use the syslog endpoint (e.g., `logs.papertrailapp.com:<port>`).
4. Select the services to forward logs from.
5. Save and verify that logs appear in the external service.

### Environment-Specific Configuration

Use different log drains for production and staging environments to keep
log streams separate. Configure the log level per environment:

```
# Production
NIC_LOG_LEVEL=INFO

# Staging / Development
NIC_LOG_LEVEL=DEBUG
```

## Log Format Reference

### Standard Application Logs

All application logs follow the JSON format described above. Key log sources:

| Logger | Purpose |
|--------|---------|
| `nic.api.*` | API request handling, route-level logging |
| `nic.services.*` | Business logic (clustering, embedding, ingestion) |
| `nic.core.database` | Database connection pool events |
| `nic.core.auth` | Authentication and authorization |
| `nic.core.rate_limit` | Rate limiting events |

### Filtering by Request ID

The `X-Request-ID` header is propagated through the logging context. To trace
a specific request across all log entries:

```
# Example query (Datadog)
@request_id:abc-123-def

# Example query (Loki / LogQL)
{app="nic-api"} |= "abc-123-def"
```
