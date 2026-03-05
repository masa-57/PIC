"""PIC — Image Clustering API application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded

from pic.api.health import router as health_router
from pic.api.router import api_router, browser_router
from pic.config import settings
from pic.core.auth import verify_api_key
from pic.core.database import engine
from pic.core.exception_handlers import (
    http_exception_handler,
    rate_limit_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from pic.core.logging import setup_logging
from pic.core.middleware import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    access_log_middleware,
    cache_control_middleware,
    etag_middleware,
)
from pic.core.rate_limit import limiter

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

# Exception handlers
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]

# Middleware (order matters: outermost first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID", "Authorization"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)

Instrumentator().instrument(app).expose(app, include_in_schema=False, dependencies=[Depends(verify_api_key)])

# HTTP middleware (registered via @app.middleware, applied in reverse order)
app.middleware("http")(access_log_middleware)
app.middleware("http")(cache_control_middleware)
app.middleware("http")(etag_middleware)

# Routers
app.include_router(api_router)
app.include_router(browser_router)
app.include_router(health_router)

# Serve local storage files when using local backend
if settings.storage_backend == "local":
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/files",
        StaticFiles(directory=str(settings.local_storage_path)),
        name="local_storage",
    )
    logger.info("Mounted local storage at /files -> %s", settings.local_storage_path)


def main() -> None:
    """Console entrypoint for `pic` command."""
    import uvicorn

    uvicorn.run("pic.main:app", host="127.0.0.1", port=8000)
