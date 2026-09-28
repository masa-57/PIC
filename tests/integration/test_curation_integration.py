"""Integration tests for product curation against real PostgreSQL (#113)."""

import pytest
from sqlalchemy import select

from pic.models.db import Image, Product
from pic.services import curation


async def _member_ids(db, product_id: int) -> set[str]:
    result = await db.execute(select(Image.id).where(Image.product_id == product_id))
    return set(result.scalars())


@pytest.mark.integration
class TestCreateProduct:
    async def test_merges_several_groups_into_one_product(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        g2, imgs2 = await seed_l1_group(member_count=3)

        result = await curation.create_product(db, l1_group_ids=[g1, g2], title="Mug")

        assert (result.added, result.skipped) == (5, 0)
        assert await _member_ids(db, result.product_id) == set(imgs1 + imgs2)
        product = await db.get(Product, result.product_id)
        assert product.title == "Mug"
        assert product.representative_image_id in imgs1 + imgs2

    async def test_skips_images_already_in_a_product(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        first = await curation.create_product(db, image_ids=[imgs1[0]])

        result = await curation.create_product(db, l1_group_ids=[g1])

        assert (result.added, result.skipped) == (1, 1)
        assert await _member_ids(db, first.product_id) == {imgs1[0]}
        assert await _member_ids(db, result.product_id) == {imgs1[1]}

    async def test_rejects_when_every_image_is_taken(self, db, seed_l1_group):
        g1, _ = await seed_l1_group(member_count=2)
        await curation.create_product(db, l1_group_ids=[g1])

        with pytest.raises(curation.EmptySelectionError):
            await curation.create_product(db, l1_group_ids=[g1])

    async def test_rejects_empty_selection(self, db):
        with pytest.raises(curation.EmptySelectionError):
            await curation.create_product(db)

    async def test_unknown_group_raises_not_found(self, db):
        with pytest.raises(curation.NotFoundError, match="999999"):
            await curation.create_product(db, l1_group_ids=[999999])

    async def test_unknown_image_raises_not_found(self, db):
        with pytest.raises(curation.NotFoundError):
            await curation.create_product(db, image_ids=["no-such-image"])


@pytest.mark.integration
class TestAddToProduct:
    async def test_adds_free_images_and_skips_other_products(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        g2, imgs2 = await seed_l1_group(member_count=2)
        target = await curation.create_product(db, l1_group_ids=[g1])
        other = await curation.create_product(db, image_ids=[imgs2[0]])

        result = await curation.add_to_product(db, target.product_id, l1_group_ids=[g2])

        assert (result.added, result.skipped) == (1, 1)
        assert await _member_ids(db, target.product_id) == {*imgs1, imgs2[1]}
        assert await _member_ids(db, other.product_id) == {imgs2[0]}

    async def test_images_already_in_target_are_not_counted_as_skipped(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        target = await curation.create_product(db, l1_group_ids=[g1])

        result = await curation.add_to_product(db, target.product_id, image_ids=imgs1)

        assert (result.added, result.skipped) == (0, 0)

    async def test_missing_product_raises_not_found(self, db, seed_l1_group):
        g1, _ = await seed_l1_group(member_count=1)
        with pytest.raises(curation.NotFoundError):
            await curation.add_to_product(db, 999999, l1_group_ids=[g1])
