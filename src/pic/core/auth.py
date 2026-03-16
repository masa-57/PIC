"""API key authentication dependency."""

import hmac
import logging
from enum import StrEnum

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from pic.config import settings

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthMode(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    MISCONFIGURED = "misconfigured"


def _is_auth_disabled() -> bool:
    value = getattr(settings, "auth_disabled", False)
    return value if isinstance(value, bool) else False


def _env_name() -> str:
    value = getattr(settings, "env", "development")
    return value.lower() if isinstance(value, str) else "development"


def get_auth_mode() -> AuthMode:
    if settings.api_key:
        return AuthMode.ENABLED
    if _is_auth_disabled():
        return AuthMode.DISABLED
    return AuthMode.MISCONFIGURED


def log_auth_mode() -> None:
    """Log the effective authentication mode during startup."""
    env = _env_name()
    auth_mode = get_auth_mode()

    if auth_mode == AuthMode.ENABLED:
        logger.info("Authentication enabled with PIC_API_KEY (env=%s)", env)
        return
    if auth_mode == AuthMode.DISABLED:
        logger.warning("Authentication disabled explicitly via PIC_AUTH_DISABLED=true (env=%s)", env)
        return

    logger.error(
        "Authentication is not configured (env=%s): set PIC_API_KEY or PIC_AUTH_DISABLED=true. "
        "Protected endpoints will return 503 until auth is configured.",
        env,
    )


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Validate the API key using the explicit opt-out auth model."""
    auth_mode = get_auth_mode()
    if auth_mode == AuthMode.DISABLED:
        return
    if auth_mode == AuthMode.MISCONFIGURED:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if not api_key or not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
