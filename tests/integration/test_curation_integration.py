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


@pytest.mark.integration
class TestRemoveFromProduct:
    async def test_removes_images_and_reassigns_representative(self, db, seed_l1_group):
        g1, imgs = await seed_l1_group(member_count=3)
        created = await curation.create_product(db, l1_group_ids=[g1])
        product = await db.get(Product, created.product_id)
        old_rep = product.representative_image_id

        result = await curation.remove_from_product(db, created.product_id, [old_rep])

        assert result.removed == 1
        assert result.deleted_product_ids == []
        remaining = await _member_ids(db, created.product_id)
        assert remaining == set(imgs) - {old_rep}
        await db.refresh(product)
        assert product.representative_image_id in remaining

    async def test_deletes_product_when_last_image_is_removed(self, db, seed_l1_group):
        g1, imgs = await seed_l1_group(member_count=2)
        created = await curation.create_product(db, l1_group_ids=[g1])

        result = await curation.remove_from_product(db, created.product_id, imgs)

        assert result.deleted_product_ids == [created.product_id]
        assert (await db.execute(select(Product).where(Product.id == created.product_id))).first() is None
        assert await _member_ids(db, created.product_id) == set()

    async def test_ignores_images_of_other_products(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        g2, imgs2 = await seed_l1_group(member_count=1)
        target = await curation.create_product(db, l1_group_ids=[g1])
        other = await curation.create_product(db, l1_group_ids=[g2])

        result = await curation.remove_from_product(db, target.product_id, imgs2)

        assert result.removed == 0
        assert await _member_ids(db, other.product_id) == set(imgs2)


@pytest.mark.integration
class TestSplitProduct:
    async def test_moves_selected_images_to_a_new_product(self, db, seed_l1_group):
        g1, imgs = await seed_l1_group(member_count=3)
        created = await curation.create_product(db, l1_group_ids=[g1], title="Vase")

        result = await curation.split_product(db, created.product_id, imgs[:1])

        assert result.product_id != created.product_id
        assert await _member_ids(db, result.product_id) == {imgs[0]}
        assert await _member_ids(db, created.product_id) == set(imgs[1:])
        new_product = await db.get(Product, result.product_id)
        assert new_product.title == "Vase (split)"

    async def test_rejects_splitting_every_image(self, db, seed_l1_group):
        g1, imgs = await seed_l1_group(member_count=2)
        created = await curation.create_product(db, l1_group_ids=[g1])

        with pytest.raises(curation.InvalidOperationError):
            await curation.split_product(db, created.product_id, imgs)
        assert await _member_ids(db, created.product_id) == set(imgs)

    async def test_rejects_images_not_in_the_product(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        g2, imgs2 = await seed_l1_group(member_count=1)
        created = await curation.create_product(db, l1_group_ids=[g1])
        await curation.create_product(db, l1_group_ids=[g2])

        with pytest.raises(curation.InvalidOperationError):
            await curation.split_product(db, created.product_id, [imgs1[0], imgs2[0]])
        assert await _member_ids(db, created.product_id) == set(imgs1)


@pytest.mark.integration
class TestMergeProducts:
    async def test_moves_all_images_and_deletes_source(self, db, seed_l1_group):
        g1, imgs1 = await seed_l1_group(member_count=2)
        g2, imgs2 = await seed_l1_group(member_count=2)
        target = await curation.create_product(db, l1_group_ids=[g1])
        source = await curation.create_product(db, l1_group_ids=[g2])

        result = await curation.merge_products(db, target.product_id, source.product_id)

        assert result.added == 2
        assert result.deleted_product_ids == [source.product_id]
        assert await _member_ids(db, target.product_id) == set(imgs1 + imgs2)
        assert (await db.execute(select(Product).where(Product.id == source.product_id))).first() is None

    async def test_rejects_merging_into_itself(self, db, seed_l1_group):
        g1, _ = await seed_l1_group(member_count=1)
        created = await curation.create_product(db, l1_group_ids=[g1])
        with pytest.raises(curation.InvalidOperationError):
            await curation.merge_products(db, created.product_id, created.product_id)

    async def test_missing_target_raises_not_found(self, db, seed_l1_group):
        g1, _ = await seed_l1_group(member_count=1)
        created = await curation.create_product(db, l1_group_ids=[g1])
        with pytest.raises(curation.NotFoundError):
            await curation.merge_products(db, 999999, created.product_id)


@pytest.mark.integration
class TestProductsSurviveReclustering:
    async def test_product_membership_is_unchanged_after_full_clustering(self, db, seed_images):
        from pic.services.clustering_pipeline import run_full_clustering

        image_ids = await seed_images(count=8, with_embedding=True)
        await run_full_clustering(db, {})
        created = await curation.create_product(db, image_ids=image_ids[:3], title="Keep me")

        await run_full_clustering(db, {})

        assert await _member_ids(db, created.product_id) == set(image_ids[:3])
        product = await db.get(Product, created.product_id)
        await db.refresh(product)
        assert product.title == "Keep me"
        assert product.representative_image_id in image_ids[:3]
