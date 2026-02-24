import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nic.api.deps import PaginationParams, build_pagination_links, get_db, get_or_404
from nic.models.db import Image, L1Group, Product
from nic.models.schemas import (
    CandidateListOut,
    CandidateOut,
    ProblemDetail,
    ProductCreate,
    ProductImageListOut,
    ProductImageOut,
    ProductListOut,
    ProductOut,
    ProductUpdate,
)
from nic.services.image_store import generate_presigned_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["products"])


def _is_l1_unique_conflict(exc: IntegrityError) -> bool:
    """True when unique constraint/index enforces one product per L1 group."""
    original = getattr(exc, "orig", None)
    constraint_name = getattr(original, "constraint_name", None)
    if constraint_name == "ix_images_one_product_per_l1":
        return True
    # asyncpg may only surface the name in string form depending on adapter/version
    return "ix_images_one_product_per_l1" in str(original)


def _product_to_out(product: Product, image_count: int | None = None) -> ProductOut:
    """Convert a Product ORM object to ProductOut."""
    tags: list[str] = product.tags if isinstance(product.tags, list) else []
    count = image_count if image_count is not None else len(product.images)
    return ProductOut(
        id=product.id,
        representative_image_id=product.representative_image_id,
        title=product.title,
        description=product.description,
        tags=tags,
        image_count=count,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@router.get("/candidates", response_model=CandidateListOut)
async def list_candidates(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> CandidateListOut:
    """L1 groups where no member image has a product — ready for AI processing."""
    has_product = (
        select(Image.l1_group_id)
        .where(Image.product_id.isnot(None))
        .where(Image.l1_group_id.isnot(None))
        .distinct()
        .subquery()
    )

    # Join with representative image to avoid N+1 queries
    query = (
        select(L1Group, Image.s3_key)
        .outerjoin(Image, L1Group.representative_image_id == Image.id)
        .where(L1Group.id.notin_(select(has_product.c.l1_group_id)))
        .order_by(L1Group.member_count.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    count_query = select(func.count()).select_from(L1Group).where(L1Group.id.notin_(select(has_product.c.l1_group_id)))

    result = await db.execute(query)
    total_result = await db.execute(count_query)
    rows = result.all()
    total = total_result.scalar_one()

    items: list[CandidateOut] = []
    for group, rep_s3_key in rows:
        rep_url = generate_presigned_url(rep_s3_key) if rep_s3_key else ""
        items.append(
            CandidateOut(
                l1_group_id=group.id,
                representative_image_id=group.representative_image_id,
                representative_url=rep_url,
                member_count=group.member_count,
            )
        )

    return CandidateListOut(
        items=items,
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/products/candidates", total, pagination.offset, pagination.limit),
    )


@router.post(
    "",
    response_model=ProductOut,
    status_code=201,
    responses={
        400: {"model": ProblemDetail, "description": "Invalid L1 group state"},
        404: {"model": ProblemDetail, "description": "L1 group not found"},
        409: {"model": ProblemDetail, "description": "L1 group already has a product"},
    },
)
async def create_product(
    body: ProductCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    """Create a product from an L1 group. Links all group images to the product."""
    group_result = await db.execute(select(L1Group).where(L1Group.id == body.l1_group_id).with_for_update())
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="L1 group not found")

    existing = await db.execute(
        select(exists().where(Image.l1_group_id == body.l1_group_id, Image.product_id.isnot(None)))
    )
    if existing.scalar():
        raise HTTPException(status_code=409, detail="L1 group already has a product")

    if not group.representative_image_id:
        raise HTTPException(status_code=400, detail="L1 group has no representative image")
    rep_exists = await db.execute(
        select(
            exists().where(
                Image.id == group.representative_image_id,
                Image.l1_group_id == body.l1_group_id,
            )
        )
    )
    if not rep_exists.scalar():
        raise HTTPException(status_code=400, detail="L1 group representative image not found")

    product = Product(
        representative_image_id=group.representative_image_id,
        title=body.title,
        description=body.description,
        tags=body.tags or None,
    )
    db.add(product)
    await db.flush()

    await db.execute(update(Image).where(Image.l1_group_id == body.l1_group_id).values(product_id=product.id))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _is_l1_unique_conflict(exc):
            raise HTTPException(status_code=409, detail="L1 group already has a product") from None
        raise
    await db.refresh(product)

    count_result = await db.execute(select(func.count()).select_from(Image).where(Image.product_id == product.id))
    image_count = count_result.scalar_one()

    response.headers["Location"] = f"/api/v1/products/{product.id}"
    return _product_to_out(product, image_count=image_count)


@router.get("", response_model=ProductListOut)
async def list_products(
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> ProductListOut:
    # Use subquery count instead of eager-loading all images (avoids N+1)
    image_count_subq = (
        select(Image.product_id, func.count().label("count"))
        .where(Image.product_id.isnot(None))
        .group_by(Image.product_id)
        .subquery()
    )
    query = (
        select(Product, func.coalesce(image_count_subq.c.count, 0).label("image_count"))
        .outerjoin(image_count_subq, Product.id == image_count_subq.c.product_id)
        .order_by(Product.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    count_query = select(func.count()).select_from(Product)

    result = await db.execute(query)
    total_result = await db.execute(count_query)

    rows = result.all()
    total = total_result.scalar_one()
    return ProductListOut(
        items=[_product_to_out(p, image_count=count) for p, count in rows],
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links("/api/v1/products", total, pagination.offset, pagination.limit),
    )


@router.get(
    "/{product_id}",
    response_model=ProductOut,
    responses={404: {"model": ProblemDetail, "description": "Product not found"}},
)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    product = await get_or_404(db, Product, product_id, "Product not found")
    count_result = await db.execute(select(func.count()).select_from(Image).where(Image.product_id == product.id))
    image_count = count_result.scalar_one()
    return _product_to_out(product, image_count=image_count)


@router.patch(
    "/{product_id}",
    response_model=ProductOut,
    responses={404: {"model": ProblemDetail, "description": "Product not found"}},
)
async def update_product(
    product_id: int,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProductOut:
    product = await get_or_404(db, Product, product_id, "Product not found")

    if body.title is not None:
        product.title = body.title
    if body.description is not None:
        product.description = body.description
    if body.tags is not None:
        product.tags = body.tags

    await db.commit()
    await db.refresh(product)
    count_result = await db.execute(select(func.count()).select_from(Image).where(Image.product_id == product.id))
    image_count = count_result.scalar_one()
    return _product_to_out(product, image_count=image_count)


@router.delete(
    "/{product_id}",
    status_code=204,
    responses={404: {"model": ProblemDetail, "description": "Product not found"}},
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    product = await get_or_404(db, Product, product_id, "Product not found")
    await db.delete(product)
    await db.commit()


@router.get(
    "/{product_id}/images",
    response_model=ProductImageListOut,
    responses={404: {"model": ProblemDetail, "description": "Product not found"}},
)
async def get_product_images(
    product_id: int,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> ProductImageListOut:
    """Get all images belonging to a product with presigned URLs."""
    product = await get_or_404(db, Product, product_id, "Product not found")

    total_result = await db.execute(select(func.count()).select_from(Image).where(Image.product_id == product_id))
    total = total_result.scalar_one()

    images_result = await db.execute(
        select(Image)
        .where(Image.product_id == product_id)
        .order_by(Image.created_at)
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    images = images_result.scalars().all()

    # Generate presigned URLs in parallel to avoid serial S3 signing latency
    async def _make_item(img: Image) -> ProductImageOut:
        presigned_url = await asyncio.to_thread(generate_presigned_url, img.s3_key)
        thumbnail_url = (
            await asyncio.to_thread(generate_presigned_url, img.s3_thumbnail_key) if img.s3_thumbnail_key else None
        )
        return ProductImageOut(
            image_id=img.id,
            filename=img.filename,
            presigned_url=presigned_url,
            thumbnail_url=thumbnail_url,
            is_representative=img.id == product.representative_image_id,
            width=img.width,
            height=img.height,
        )

    items = list(await asyncio.gather(*[_make_item(img) for img in images]))

    return ProductImageListOut(
        items=items,
        total=total,
        offset=pagination.offset,
        limit=pagination.limit,
        links=build_pagination_links(
            f"/api/v1/products/{product_id}/images", total, pagination.offset, pagination.limit
        ),
    )
