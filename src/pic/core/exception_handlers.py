"""Centralized exception handlers for the FastAPI application."""

import http
import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from pic.models.schemas import ProblemDetail

logger = logging.getLogger(__name__)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
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


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalize HTTPException responses to RFC 7807 ProblemDetail format."""
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
