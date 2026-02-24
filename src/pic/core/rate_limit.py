"""Rate limiting configuration (shared across API modules)."""

import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from pic.config import settings


def _get_rate_limit_key(request: Request) -> str:
    """Use hashed API key as rate-limit key for authenticated requests, IP otherwise.

    Hashing prevents timing-based key discovery through rate limit bucket probing.
    """
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"apikey:{key_hash}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=_get_rate_limit_key,
    default_limits=[settings.rate_limit_default, settings.rate_limit_burst],
)
