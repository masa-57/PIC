# Log Aggregation

This document describes how PIC logs, how to view the logs, and how to send them to an external log service.

## Current Logging Configuration

PIC uses Python's standard `logging` module with a custom `JSONFormatter` (defined in `src/pic/core/logging.py`). The API and `pic-worker` both call `setup_logging()`, which writes one JSON object per line to stdout. This is the same in every environment; there is no plain-text mode to switch on.

### Log Format

Each log entry is a JSON object. Example: an access log line from the API.

```json
{
  "timestamp": "2026-09-28T10:30:00.123456+00:00",
  "level": "INFO",
  "logger": "pic.core.middleware",
  "message": "POST /api/v1/pipeline/run 202 14.2ms [3f2a9c1e-5b7d-4e8a-9f0b-2c6d1e4a7b3c]"
}
```

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 UTC timestamp |
| `level` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `logger` | Python logger name (module path) |
| `message` | Human-readable log message |
| `exception` | Full traceback string (only when an exception is logged) |

### Access logs and request IDs

The API writes one access log line per request (logger `pic.core.middleware`), in the form `METHOD PATH STATUS LATENCYms [REQUEST_ID]`. The level is INFO for status below 400, WARNING for 4xx and ERROR for 5xx. `/health`, `/health/detailed` and `/metrics` are not logged.

The request ID is the `X-Request-ID` header sent by the client (letters, digits, `.`, `_`, `-`, up to 64 characters), or a generated UUID. It is returned in the `X-Request-ID` response header and in API error bodies. In the logs it appears only at the end of the access log message, not as a separate JSON field, and other log lines from the same request do not carry it.

### Log level

- **API**: `PIC_LOG_LEVEL` (default `INFO`; DEBUG, INFO, WARNING, ERROR or CRITICAL).
- **`pic-worker`**: always logs at `INFO`. It ignores `PIC_LOG_LEVEL`.
- **Modal functions**: they do not call `setup_logging()`, so their output is not PIC's JSON format and uses Python's default logging configuration inside Modal.

`setup_logging()` also sets `httpcore`, `httpx` and `transformers` to WARNING to cut noise.

## Viewing Logs

With Docker Compose, follow the API and worker logs with:

```bash
docker compose logs -f api worker
```

A native `pic-worker` or `fastapi` process logs to its terminal. Modal logs are in the Modal dashboard, or `uv run modal app logs pic`.

Docker keeps container logs only until the container is removed, and Modal keeps them for a limited time. For long-term storage and search, use an external service.

## External Services

Any service that ingests JSON lines from container stdout works. Some common choices:

### Grafana Loki

- Label-based indexing, cheap for high volume.
- Parses JSON at query time (`| json` in LogQL).
- Self-hostable; works with Grafana dashboards.
- Setup: Promtail / Grafana Alloy reading Docker logs, or the Loki Docker logging driver.

### Datadog

- Hosted; full-text search and field filtering.
- Log-based metrics and alerts.
- Setup: the Datadog agent with Docker log collection, or your host's log drain.

### Papertrail

- Hosted; simple syslog forwarding, live tail and search.
- Good for small deployments.
- Setup: a syslog logging driver or your host's log drain.

## Forwarding Logs

- **Docker logging driver**: add a `logging:` section (for example `syslog` or `loki`) to the `api` and `worker` services in `docker-compose.yml`.
- **Log collector**: run an agent (Promtail, Alloy, Vector, Datadog agent) that reads the Docker log files on the host.
- **Host log drain**: most container platforms can forward stdout to a log service.

Prefer these over adding a logging handler in the code: they need no code change and also capture output from before logging is set up.

### Per-environment level

```
# Production
PIC_LOG_LEVEL=INFO

# Debugging
PIC_LOG_LEVEL=DEBUG
```

With Compose, set it in the `x-pic-env` block of `docker-compose.yml` and recreate the `api` container. Compose does not read a `.env` file into the containers.

## Logger Reference

Logger names follow the module path. Main sources:

| Logger | Purpose |
|--------|---------|
| `pic.main` | API startup and shutdown, local storage mount |
| `pic.core.middleware` | Access logs (one line per request) |
| `pic.core.auth` | Authentication mode at startup |
| `pic.core.database` | Database TLS warnings at startup |
| `pic.core.exception_handlers` | Unhandled errors in API requests |
| `pic.api.*` | Route handlers (`pic.api.images`, `pic.api.products`, `pic.api.gdrive`, `pic.api.deps` for job dispatch, ...) |
| `pic.services.*` | Business logic (`pic.services.clustering`, `pic.services.embedding`, `pic.services.dispatch`, `pic.services.storage.*`, ...) |
| `pic.worker.local_runner` | `pic-worker` start/stop, each job run, orphaned job recovery |
| `pic.worker.*` | Job implementations (`pic.worker.pipeline`, `pic.worker.cluster`, `pic.worker.gdrive_sync`, `pic.worker.url_ingest`, `pic.worker.helpers`, ...) |
| `pic.modal_app` | Modal Google Drive cron checker |

The web UI (`pic.ui`) does not log on its own; its requests show up in the access log.

### Useful queries

Trace one request by its ID:

```
# Datadog
"3f2a9c1e-5b7d-4e8a-9f0b-2c6d1e4a7b3c"

# Loki / LogQL
{compose_service="api"} |= "3f2a9c1e-5b7d-4e8a-9f0b-2c6d1e4a7b3c"
```

Find failed jobs in worker logs:

```
# Loki / LogQL
{compose_service="worker"} | json | level="ERROR"
```

Label names depend on how you collect logs; adjust `compose_service` to match your setup.
