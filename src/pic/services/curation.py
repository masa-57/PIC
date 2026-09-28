"""Product curation: the durable, human-owned grouping of images.

Clustering rebuilds L1 groups and L2 clusters on every run and never touches
products. Every change to product membership goes through this module so the
web UI and the JSON API behave the same. Each public function commits once.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pic.models.db import Image, L1Group, Product


class CurationError(Exception):
    """Base curation error. ``status_code`` is what the API and UI report."""

    status_code = 400


class NotFoundError(CurationError):
    status_code = 404


class EmptySelectionError(CurationError):
    status_code = 409


class InvalidOperationError(CurationError):
    status_code = 400


@dataclass
class CurationResult:
    product_id: int | None
    added: int = 0
    skipped: int = 0
    removed: int = 0
    deleted_product_ids: list[int] = field(default_factory=list)


async def create_product(
    db: AsyncSession,
    *,
    l1_group_ids: Sequence[int] = (),
    image_ids: Sequence[str] = (),
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> CurationResult:
    """Create a product from the selected groups and images that are in no product yet."""
    selected = await _resolve_selection(db, l1_group_ids, image_ids)
    free_result = await db.execute(
        select(Image.id)
        .where(Image.id.in_(selected), Image.product_id.is_(None))
        .order_by(Image.created_at, Image.id)
        .with_for_update()
    )
    free = list(free_result.scalars())
    if not free:
        raise EmptySelectionError("Every selected image already belongs to a product")

    product = Product(representative_image_id=free[0], title=title, description=description, tags=tags or None)
    db.add(product)
    await db.flush()
    await db.execute(update(Image).where(Image.id.in_(free)).values(product_id=product.id))
    await db.commit()
    return CurationResult(product_id=product.id, added=len(free), skipped=len(selected) - len(free))


async def add_to_product(
    db: AsyncSession,
    product_id: int,
    *,
    l1_group_ids: Sequence[int] = (),
    image_ids: Sequence[str] = (),
) -> CurationResult:
    """Add selected images that are in no product. Images in another product are skipped."""
    product = await _get_product(db, product_id)
    selected = await _resolve_selection(db, l1_group_ids, image_ids)
    result = await db.execute(
        update(Image).where(Image.id.in_(selected), Image.product_id.is_(None)).values(product_id=product.id)
    )
    in_product = await db.scalar(
        select(func.count()).select_from(Image).where(Image.id.in_(selected), Image.product_id == product.id)
    )
    await db.commit()
    return CurationResult(product_id=product.id, added=_rowcount(result), skipped=len(selected) - int(in_product or 0))


async def remove_from_product(db: AsyncSession, product_id: int, image_ids: Sequence[str]) -> CurationResult:
    """Unlink images from a product. A product left with no images is deleted."""
    product = await _get_product(db, product_id)
    result = await db.execute(
        update(Image).where(Image.id.in_(list(image_ids)), Image.product_id == product.id).values(product_id=None)
    )
    outcome = CurationResult(product_id=product.id, removed=_rowcount(result))
    await _fix_representative(db, product, outcome)
    await db.commit()
    return outcome


async def split_product(db: AsyncSession, product_id: int, image_ids: Sequence[str]) -> CurationResult:
    """Move some of a product's images into a new product. Returns the new product's id."""
    product = await _get_product(db, product_id)
    chosen = set(image_ids)
    if not chosen:
        raise EmptySelectionError("Select at least one image")
    members = set((await db.execute(select(Image.id).where(Image.product_id == product.id))).scalars())
    if not chosen <= members:
        raise InvalidOperationError("Some selected images are no longer in this product; reload the page")
    if chosen == members:
        raise InvalidOperationError("Select fewer than all images to split a product")

    first = await db.scalar(select(Image.id).where(Image.id.in_(chosen)).order_by(Image.created_at, Image.id).limit(1))
    new_product = Product(
        representative_image_id=first,
        title=f"{product.title} (split)" if product.title else None,
    )
    db.add(new_product)
    await db.flush()
    await db.execute(update(Image).where(Image.id.in_(chosen)).values(product_id=new_product.id))
    outcome = CurationResult(product_id=new_product.id, added=len(chosen))
    await _fix_representative(db, product, outcome)
    await db.commit()
    return outcome


async def merge_products(db: AsyncSession, target_id: int, source_id: int) -> CurationResult:
    """Move every image of the source product into the target and delete the source."""
    if target_id == source_id:
        raise InvalidOperationError("Cannot merge a product into itself")
    target = await _get_product(db, target_id)
    source = await _get_product(db, source_id)
    result = await db.execute(update(Image).where(Image.product_id == source.id).values(product_id=target.id))
    await _delete_product(db, source)
    await db.commit()
    return CurationResult(product_id=target.id, added=_rowcount(result), deleted_product_ids=[source_id])


async def _fix_representative(db: AsyncSession, product: Product, outcome: CurationResult) -> None:
    """Keep the representative if it is still a member; else pick the oldest member or delete the product."""
    still_member = await db.scalar(
        select(exists().where(Image.id == product.representative_image_id, Image.product_id == product.id))
    )
    if still_member:
        return
    replacement = await db.scalar(
        select(Image.id).where(Image.product_id == product.id).order_by(Image.created_at, Image.id).limit(1)
    )
    if replacement is None:
        outcome.deleted_product_ids.append(product.id)
        await _delete_product(db, product)
    else:
        product.representative_image_id = replacement


async def _delete_product(db: AsyncSession, product: Product) -> None:
    # Core DELETE: images.product_id is ON DELETE SET NULL, and this avoids lazy-loading product.images.
    await db.execute(delete(Product).where(Product.id == product.id))
    db.expunge(product)


async def _get_product(db: AsyncSession, product_id: int) -> Product:
    result = await db.execute(select(Product).where(Product.id == product_id).with_for_update())
    product = result.scalar_one_or_none()
    if product is None:
        raise NotFoundError(f"Product {product_id} not found")
    return product


async def _resolve_selection(db: AsyncSession, l1_group_ids: Sequence[int], image_ids: Sequence[str]) -> list[str]:
    """Expand groups to their images and check everything exists. Returns sorted image ids."""
    if not l1_group_ids and not image_ids:
        raise EmptySelectionError("Select at least one group or image")
    selected: set[str] = set()
    if l1_group_ids:
        wanted_groups = set(l1_group_ids)
        found_groups = set((await db.execute(select(L1Group.id).where(L1Group.id.in_(wanted_groups)))).scalars())
        if missing_groups := wanted_groups - found_groups:
            raise NotFoundError(f"L1 group not found: {', '.join(map(str, sorted(missing_groups)))}")
        selected.update((await db.execute(select(Image.id).where(Image.l1_group_id.in_(wanted_groups)))).scalars())
    if image_ids:
        wanted_images = set(image_ids)
        found_images = set((await db.execute(select(Image.id).where(Image.id.in_(wanted_images)))).scalars())
        if missing_images := wanted_images - found_images:
            raise NotFoundError(f"Image not found: {', '.join(sorted(missing_images))}")
        selected.update(found_images)
    return sorted(selected)


def _rowcount(result: Any) -> int:  # noqa: ANN401
    return int(result.rowcount or 0)
