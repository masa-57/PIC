"""Integration tests for URL-based image ingestion."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.integration
class TestUrlIngestEndpoint:
    async def test_ingest_returns_202_with_job_id(self, client):
        """POST /images/ingest should accept URLs and return a job ID."""
        with patch(
            "pic.api.images.submit_url_ingest_job",
            new_callable=AsyncMock,
            return_value="mock-call-id",
        ):
            response = await client.post(
                "/api/v1/images/ingest",
                json={"urls": ["https://example.com/photo.jpg"]},
            )
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["urls_submitted"] == 1

    async def test_ingest_rejects_empty_urls(self, client):
        response = await client.post(
            "/api/v1/images/ingest",
            json={"urls": []},
        )
        assert response.status_code == 422

    async def test_ingest_rejects_too_many_urls(self, client):
        urls = [f"https://example.com/img{i}.jpg" for i in range(101)]
        response = await client.post(
            "/api/v1/images/ingest",
            json={"urls": urls},
        )
        assert response.status_code == 422

    async def test_ingest_rejects_invalid_urls(self, client):
        response = await client.post(
            "/api/v1/images/ingest",
            json={"urls": ["not-a-valid-url"]},
        )
        assert response.status_code == 422

    async def test_ingest_multiple_urls(self, client):
        """POST /images/ingest with multiple valid URLs."""
        with patch(
            "pic.api.images.submit_url_ingest_job",
            new_callable=AsyncMock,
            return_value="mock-call-id",
        ):
            response = await client.post(
                "/api/v1/images/ingest",
                json={
                    "urls": [
                        "https://example.com/a.jpg",
                        "https://example.com/b.png",
                        "https://example.com/c.webp",
                    ],
                    "auto_pipeline": True,
                },
            )
        assert response.status_code == 202
        data = response.json()
        assert data["urls_submitted"] == 3
