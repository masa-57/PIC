"""E2E health check tests against a running API instance."""

import httpx
import pytest


@pytest.mark.e2e
async def test_health_endpoint(e2e_client: httpx.AsyncClient):
    """GET /health returns ok or degraded status."""
    resp = await e2e_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "database" in data


@pytest.mark.e2e
async def test_health_has_no_cache_header(e2e_client: httpx.AsyncClient):
    """GET /health returns Cache-Control: no-cache."""
    resp = await e2e_client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-cache"


@pytest.mark.e2e
async def test_detailed_health_endpoint(e2e_client: httpx.AsyncClient):
    """GET /health/detailed returns database and job health info."""
    resp = await e2e_client.get("/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert "database" in data
    assert "status" in data
    assert "recent_failed_jobs" in data
