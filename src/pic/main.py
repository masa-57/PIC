"""PIC — Image Clustering API application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from pic.api.health import router as health_router
from pic.api.router import api_router
from pic.config import settings
from pic.core.auth import log_auth_mode, verify_api_key
from pic.core.database import engine
from pic.core.exception_handlers import (
    http_exception_handler,
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
from pic.ui import STATIC_DIR
from pic.ui.auth import LoginRequiredError, login_required_handler
from pic.ui.routes import legacy_router as ui_legacy_router
from pic.ui.routes import public_router as ui_public_router
from pic.ui.routes import router as ui_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(level=getattr(logging, settings.log_level))
    log_auth_mode()
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

# Exception handlers
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(LoginRequiredError, login_required_handler)

# Middleware (order matters: outermost first)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)

Instrumentator().instrument(app).expose(app, include_in_schema=False, dependencies=[Depends(verify_api_key)])

# HTTP middleware (registered via @app.middleware, applied in reverse order)
app.middleware("http")(access_log_middleware)
app.middleware("http")(cache_control_middleware)
app.middleware("http")(etag_middleware)

# Routers
app.include_router(api_router)
app.include_router(ui_legacy_router)
app.include_router(health_router)
app.include_router(ui_public_router)
app.include_router(ui_router)
app.mount("/ui/static", StaticFiles(directory=str(STATIC_DIR)), name="ui_static")

# Serve local storage files when using local backend
if settings.storage_backend == "local":
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
