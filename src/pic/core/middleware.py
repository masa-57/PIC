"""HTTP middleware for security headers, request size limits, logging, caching, and ETags."""

import hashlib
import logging
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pic.config import settings

logger = logging.getLogger(__name__)

_ACCESS_LOG_SKIP_PATHS = {"/health", "/health/detailed", "/metrics"}
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _sanitize_request_id(request_id: str | None) -> str:
    """Allow only safe request-id characters to prevent header/log injection."""
    if request_id and _REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return str(uuid.uuid4())


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


async def access_log_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    """Assign request ID, log access, and expose rate limit headers."""
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
