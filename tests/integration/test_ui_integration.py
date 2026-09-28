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

    async def test_make_split_and_merge_through_the_ui(self, client, db, seed_l1_group):
        from sqlalchemy import select

        from pic.models.db import Image, Product

        hx = {"HX-Request": "true"}
        g1, imgs1 = await seed_l1_group(member_count=3)
        g2, imgs2 = await seed_l1_group(member_count=1)

        made = await client.post("/ui/clusters/unclustered/make-product", data={"group_ids": [str(g1)]}, headers=hx)
        assert made.status_code == 200
        product_id = (await db.execute(select(Product.id))).scalar_one()

        split = await client.post(f"/ui/products/{product_id}/split", data={"image_ids": [imgs1[0]]}, headers=hx)
        assert split.status_code == 200
        ids = sorted((await db.execute(select(Product.id))).scalars())
        assert len(ids) == 2

        other = next(i for i in ids if i != product_id)
        merged = await client.post(f"/ui/products/{other}/merge-into", data={"target_id": str(product_id)}, headers=hx)
        assert merged.headers["HX-Redirect"] == f"/ui/products/{product_id}"
        members = set((await db.execute(select(Image.id).where(Image.product_id == product_id))).scalars())
        assert members == set(imgs1)

    async def test_selected_images_split_a_mixed_group(self, client, db, seed_l1_group):
        from sqlalchemy import select

        from pic.models.db import Image

        group_id, imgs = await seed_l1_group(member_count=3)
        response = await client.post(
            "/ui/clusters/unclustered/make-product",
            data={"image_ids": imgs[:2]},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        linked = {
            row.id: row.product_id
            for row in (await db.execute(select(Image.id, Image.product_id).where(Image.l1_group_id == group_id))).all()
        }
        product_ids = {linked[i] for i in imgs[:2]}
        assert len(product_ids) == 1
        assert None not in product_ids
        assert linked[imgs[2]] is None
