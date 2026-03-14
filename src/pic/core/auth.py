"""API key authentication dependency."""

import hmac
import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from pic.config import settings

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _is_auth_disabled() -> bool:
    value = getattr(settings, "auth_disabled", False)
    return value if isinstance(value, bool) else False


def _env_name() -> str:
    value = getattr(settings, "env", "development")
    return value.lower() if isinstance(value, str) else "development"


_env = _env_name()
_auth_disabled = _is_auth_disabled()

if not settings.api_key and (_auth_disabled or _env != "production"):
    logger.warning(
        "PIC_API_KEY not set. Authentication is disabled for non-production usage. "
        "Set PIC_AUTH_DISABLED=true to acknowledge unauthenticated mode explicitly."
    )


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Validate the API key. If no key is configured, auth is disabled (dev mode)."""
    env = _env_name()
    auth_disabled = _is_auth_disabled()
    if not settings.api_key:
        if auth_disabled or env != "production":
            return
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if not api_key or not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
