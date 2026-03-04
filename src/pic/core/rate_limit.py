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


def create_limiter() -> Limiter:
    """Create a Limiter instance with the configured storage backend.

    When ``rate_limit_storage_url`` is set (e.g. ``redis://localhost:6379``),
    rate limit counters are stored in the shared backend so all API instances
    enforce a single set of limits.  When empty, an in-memory store is used
    (suitable for single-instance deployments and local development).
    """
    kwargs: dict[str, object] = {
        "key_func": _get_rate_limit_key,
        "default_limits": [settings.rate_limit_default, settings.rate_limit_burst],
    }
    if settings.rate_limit_storage_url:
        kwargs["storage_uri"] = settings.rate_limit_storage_url
    return Limiter(**kwargs)  # type: ignore[arg-type]


limiter = create_limiter()
