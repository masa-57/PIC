"""API key authentication dependency."""

import hmac
import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from nic.config import settings

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

if not settings.api_key:
    logger.warning("NIC_API_KEY not set — authentication is disabled")


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Validate the API key. If no key is configured, auth is disabled (dev mode)."""
    if not settings.api_key:
        return
    if not api_key or not hmac.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
