"""Web UI pages rendered against real PostgreSQL (#113)."""

import pytest

from pic.config import settings


@pytest.fixture(autouse=True)
def local_storage(monkeypatch, tmp_path):
    """Thumbnail URLs must not need S3 credentials in tests (the app mounts the local root)."""
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_storage_path", tmp_path)


@pytest.mark.integration
class TestUiPages:
    async def test_cluster_pages_render_seeded_groups(self, client, seed_l1_group):
        group_id, _ = await seed_l1_group(member_count=2)

        home = await client.get("/ui")
        assert home.status_code == 200
        assert "/ui/clusters/unclustered" in home.text

        detail = await client.get("/ui/clusters/unclustered")
        assert detail.status_code == 200
        assert f"Group {group_id}" in detail.text
