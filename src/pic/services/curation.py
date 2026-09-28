"""Product curation: the durable, human-owned grouping of images.

Clustering rebuilds L1 groups and L2 clusters on every run and never touches
products. Every change to product membership goes through this module so the
web UI and the JSON API behave the same. Each public function commits once.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
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
