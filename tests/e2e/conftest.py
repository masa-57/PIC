"""E2E test fixtures -- tests against a running API instance."""

import os

import httpx
import pytest


@pytest.fixture
def e2e_base_url() -> str:
    """Base URL for the running API under test."""
    return os.environ.get("PIC_E2E_BASE_URL", "http://localhost:8000")


@pytest.fixture
def e2e_api_key() -> str:
    """API key for authenticated E2E requests (empty = auth disabled)."""
    return os.environ.get("PIC_E2E_API_KEY", "")


@pytest.fixture
async def e2e_client(e2e_base_url: str, e2e_api_key: str):
    """Async HTTP client targeting a running API."""
    headers = {}
    if e2e_api_key:
        headers["X-API-Key"] = e2e_api_key
    async with httpx.AsyncClient(base_url=e2e_base_url, headers=headers, timeout=30) as client:
        yield client
