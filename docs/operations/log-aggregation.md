# Log Aggregation

This document describes the PIC project's logging configuration, Railway's built-in
log viewer, and recommended external log aggregation services.

## Current Logging Configuration

PIC uses Python's standard `logging` module with a custom `JSONFormatter`
(defined in `src/pic/core/logging.py`). In production, all log output is
structured JSON written to stdout.

### Log Format

Each log entry is a JSON object with the following fields:

```json
{
  "timestamp": "2025-01-15T10:30:00.123456+00:00",
  "level": "INFO",
  "logger": "pic.api.routes.images",
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

The log level is controlled by the `PIC_LOG_LEVEL` environment variable
(default: `INFO`). The `setup_logging()` function in `src/pic/core/logging.py`
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

## Forwarding Logs to External Services

Railway does not natively support log drains. To forward logs to an external
aggregation service, use one of these approaches:

- **Railway CLI streaming**: Pipe `railway logs` output to your log service.
- **Application-level forwarding**: Add a Python logging handler that sends
  logs directly to your aggregation service (e.g., Datadog's `datadog_logger`,
  Loki's `python-logging-loki`, or Papertrail's `SysLogHandler`).
- **Railway Observability Integrations**: Check the Railway dashboard for
  available third-party integrations under project settings.

### Environment-Specific Configuration

Configure the log level per environment:

```
# Production
PIC_LOG_LEVEL=INFO

# Staging / Development
PIC_LOG_LEVEL=DEBUG
```

## Log Format Reference

### Standard Application Logs

All application logs follow the JSON format described above. Key log sources:

| Logger | Purpose |
|--------|---------|
| `pic.api.*` | API request handling, route-level logging |
| `pic.services.*` | Business logic (clustering, embedding, ingestion) |
| `pic.core.database` | Database connection pool events |
| `pic.core.auth` | Authentication and authorization |
| `pic.core.rate_limit` | Rate limiting events |

### Filtering by Request ID

The `X-Request-ID` header is propagated through the logging context. To trace
a specific request across all log entries:

```
# Example query (Datadog)
@request_id:abc-123-def

# Example query (Loki / LogQL)
{app="pic-api"} |= "abc-123-def"
```
