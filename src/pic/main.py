import hashlib
import http
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import sentry_sdk
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select, text
from starlette.middleware.base import BaseHTTPMiddleware

from pic.api.router import api_router, browser_router
from pic.config import settings
from pic.core.auth import verify_api_key
from pic.core.database import async_session, engine, get_pool_status
from pic.core.logging import setup_logging
from pic.core.rate_limit import limiter
from pic.models.db import Job, JobStatus
from pic.models.schemas import DetailedHealthOut, HealthOut, PoolStatusOut, ProblemDetail
from pic.worker.helpers import check_modal_job_status, sweep_stale_jobs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(level=getattr(logging, settings.log_level))
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
        )
        logger.info("Sentry error tracking enabled")
    if settings.cors_origins == ["*"]:
        logger.warning("CORS is set to allow all origins — restrict cors_origins in production")
    logger.info("PIC starting up")
    yield
    await engine.dispose()
    logger.info("PIC shut down")


app = FastAPI(
    title="PIC — Image Clustering API",
    description="Hierarchical image clustering with near-duplicate detection and semantic similarity",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return 429 with Retry-After header so clients know when to retry."""
    retry_after = getattr(exc, "retry_after", 60)
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=429,
        content=ProblemDetail(
            title="Too Many Requests",
            status=429,
            detail=str(exc.detail),
            instance=str(request.url.path),
            request_id=request_id,
        ).model_dump(),
        headers={"Retry-After": str(retry_after)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID", "Authorization"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    _DOCS_PATHS = {"/docs", "/redoc", "/openapi.json"}
    _HTML_VIEW_PATHS = {"/api/v1/clusters/view"}

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path in self._DOCS_PATHS:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; img-src 'self' data: cdn.jsdelivr.net"
            )
        elif request.url.path in self._HTML_VIEW_PATHS:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                f"img-src {settings.s3_endpoint_url} data:; frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response


app.add_middleware(SecurityHeadersMiddleware)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than the configured limit.

    Checks Content-Length header for early rejection *and* enforces the limit
    while consuming the body stream so chunked/headerless requests cannot bypass it.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Maximum size: {settings.max_upload_size_mb}MB"},
            )

        # For requests without Content-Length (e.g. chunked), enforce by reading the stream
        if request.method in {"POST", "PUT", "PATCH"} and not content_length:
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large. Maximum size: {settings.max_upload_size_mb}MB"},
                    )

            # Starlette requires us to replace the receive so downstream can read the body
            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": body}

            request._receive = receive

        response: Response = await call_next(request)
        return response


app.add_middleware(RequestSizeLimitMiddleware)

Instrumentator().instrument(app).expose(app, include_in_schema=False, dependencies=[Depends(verify_api_key)])


_ACCESS_LOG_SKIP_PATHS = {"/health", "/health/detailed", "/metrics"}
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _sanitize_request_id(request_id: str | None) -> str:
    """Allow only safe request-id characters to prevent header/log injection."""
    if request_id and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return str(uuid.uuid4())


@app.middleware("http")
async def access_log_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    request_id = _sanitize_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    start = time.perf_counter()
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    # Expose rate limit configuration to clients
    if request.url.path.startswith("/api/"):
        response.headers["X-RateLimit-Limit"] = settings.rate_limit_default

    if request.url.path not in _ACCESS_LOG_SKIP_PATHS:
        latency_ms = (time.perf_counter() - start) * 1000
        status = response.status_code
        log_fn = logger.info if status < 400 else (logger.warning if status < 500 else logger.error)
        log_fn(
            "%s %s %d %.1fms [%s]",
            request.method,
            request.url.path,
            status,
            latency_ms,
            request_id,
        )

    return response


@app.middleware("http")
async def cache_control_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Set Cache-Control headers on GET responses based on path patterns."""
    response: Response = await call_next(request)
    if request.method != "GET" or response.status_code >= 400:
        return response
    path = request.url.path
    if path.startswith("/health"):
        response.headers["Cache-Control"] = "no-cache"
    elif path.endswith("/file"):
        response.headers["Cache-Control"] = "private, max-age=300"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, max-age=60"
    return response


@app.middleware("http")
async def etag_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Add ETag headers to GET responses and handle If-None-Match."""
    raw_response: Response = await call_next(request)
    if request.method != "GET" or raw_response.status_code >= 400:
        return raw_response
    # Only for JSON API responses
    if not request.url.path.startswith(("/api/", "/health")):
        return raw_response

    # Read body to compute ETag.
    # call_next returns starlette.middleware.base._StreamingResponse which has
    # body_iterator but is not a subclass of StreamingResponse, so use hasattr.
    if not hasattr(raw_response, "body_iterator"):
        return raw_response
    body = b""
    async for chunk in raw_response.body_iterator:
        if isinstance(chunk, bytes):
            body += chunk
        elif isinstance(chunk, memoryview):
            body += bytes(chunk)
        else:
            body += chunk.encode()

    etag = f'"{hashlib.md5(body).hexdigest()}"'  # noqa: S324
    raw_response.headers["ETag"] = etag

    # Check If-None-Match
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})

    return Response(
        content=body,
        status_code=raw_response.status_code,
        headers=dict(raw_response.headers),
        media_type=raw_response.media_type,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ProblemDetail(
            title="Internal Server Error",
            status=500,
            detail="Internal server error",
            instance=str(request.url.path),
            request_id=request_id,
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    try:
        title = http.HTTPStatus(exc.status_code).phrase
    except ValueError:
        title = "Error"
    return JSONResponse(
        status_code=exc.status_code,
        content=ProblemDetail(
            title=title,
            status=exc.status_code,
            detail=detail,
            instance=str(request.url.path),
            request_id=request_id,
        ).model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Normalize Pydantic 422 errors to match RFC 7807 format."""
    request_id = getattr(request.state, "request_id", None)
    errors = exc.errors()
    messages = []
    for err in errors:
        loc = " → ".join(str(p) for p in err["loc"] if p != "body")
        messages.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    detail = "; ".join(messages) if messages else "Validation error"
    # Sanitize errors for JSON serialization (ctx may contain non-serializable objects like ValueError)
    safe_errors = []
    for err in errors:
        safe_err = {k: v for k, v in err.items() if k != "ctx"}
        if "ctx" in err:
            safe_err["ctx"] = {k: str(v) for k, v in err["ctx"].items()}
        safe_errors.append(safe_err)
    return JSONResponse(
        status_code=422,
        content={
            **ProblemDetail(
                title="Unprocessable Entity",
                status=422,
                detail=detail,
                instance=str(request.url.path),
                request_id=request_id,
            ).model_dump(),
            "errors": safe_errors,
        },
    )


app.include_router(api_router)
app.include_router(browser_router)


@app.get("/health", response_model=HealthOut)
@limiter.limit("30/minute")
async def health_check(request: Request) -> HealthOut:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("Database health check failed")
        db_status = "error"

    return HealthOut(
        status="ok" if db_status == "connected" else "degraded",
        database=db_status,
    )


@app.get("/health/detailed", response_model=DetailedHealthOut, dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def detailed_health_check(request: Request) -> DetailedHealthOut:
    """Detailed health check for external monitoring (Railway, UptimeRobot)."""
    # Database check
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("Database health check failed")
        db_status = "error"

    # Recent job failures (last hour) + sweep stale RUNNING jobs + check Modal
    failed_count = 0
    stale_swept = 0
    try:
        async with async_session() as db:
            stale_swept = await sweep_stale_jobs(db)

            # Proactively detect Modal function failures
            try:
                await check_modal_job_status(db)
            except Exception:
                logger.warning("Modal job status check failed (non-fatal)", exc_info=True)

            one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
            result = await db.execute(
                select(func.count())
                .select_from(Job)
                .where(Job.status == JobStatus.FAILED, Job.completed_at >= one_hour_ago)
            )
            failed_count = result.scalar_one()
    except Exception:
        logger.warning("Failed to query recent job failures", exc_info=True)

    overall = "ok"
    if db_status != "connected":
        overall = "degraded"
    elif failed_count > 5:
        overall = "warning"

    return DetailedHealthOut(
        status=overall,
        database=db_status,
        recent_failed_jobs=failed_count,
        stale_jobs_swept=stale_swept,
        connection_pool=PoolStatusOut(**get_pool_status()),
    )


def main() -> None:
    """Console entrypoint for `pic` command."""
    import uvicorn

    uvicorn.run("pic.main:app", host="127.0.0.1", port=8000)
