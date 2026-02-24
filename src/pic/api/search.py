import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pic.api.deps import PaginationParams, get_db, get_or_404
from pic.config import settings
from pic.core.rate_limit import limiter
from pic.models.db import Image
from pic.models.schemas import DuplicateSearchRequest, ProblemDetail, SearchRequest, SearchResult, SearchResultsOut
from pic.services.hash_utils import hex_to_bitstring
from pic.services.vector_store import find_similar_images

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.post(
    "/similar",
    response_model=SearchResultsOut,
    responses={
        400: {"model": ProblemDetail, "description": "Image has no embedding"},
        404: {"model": ProblemDetail, "description": "Query image not found"},
    },
)
@limiter.limit("30/minute")
async def search_similar(
    request: Request,
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResultsOut:
    """Find semantically similar images using DINOv2 embeddings + pgvector k-NN."""
    query_image = await get_or_404(db, Image, body.image_id, "Query image not found")
    if not query_image.has_embedding:
        raise HTTPException(status_code=400, detail="Query image has no embedding yet")

    similar = await find_similar_images(
        db=db,
        image_id=body.image_id,
        n_results=body.n_results,
    )

    return SearchResultsOut(
        query_image_id=body.image_id,
        results=similar,
    )


@router.post(
    "/duplicates",
    response_model=SearchResultsOut,
    responses={
        400: {"model": ProblemDetail, "description": "Image has no perceptual hash"},
        404: {"model": ProblemDetail, "description": "Query image not found"},
    },
)
@limiter.limit("30/minute")
async def search_duplicates(
    request: Request,
    body: DuplicateSearchRequest,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> SearchResultsOut:
    """Find near-duplicate images using perceptual hash matching (SQL-side Hamming distance)."""
    query_image = await get_or_404(db, Image, body.image_id, "Query image not found")
    if not query_image.phash:
        raise HTTPException(status_code=400, detail="Query image has no perceptual hash yet")

    threshold = body.threshold or settings.l1_hash_threshold
    return await _do_duplicate_search(
        db=db,
        image_id=body.image_id,
        phash=query_image.phash,
        threshold=threshold,
        pagination=pagination,
    )


async def _do_duplicate_search(
    *,
    db: AsyncSession,
    image_id: str,
    phash: str,
    threshold: int,
    pagination: PaginationParams,
) -> SearchResultsOut:
    """Shared logic for duplicate search using SQL-side bit_count for Hamming distance."""
    max_bits = settings.phash_size * settings.phash_size

    try:
        query_bits = hex_to_bitstring(phash, bit_length=max_bits)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid phash format in database: {e}") from e

    # Validate bitstring contains only 0/1 to prevent injection, then embed
    # as a B'...' literal. asyncpg cannot bind Python str to BIT params, and
    # :: cast syntax conflicts with asyncpg parameter translation.
    if not all(c in "01" for c in query_bits):
        raise HTTPException(status_code=400, detail="Invalid phash: non-binary characters in hash")

    sql = f"""
        SELECT id, filename, s3_key, l1_group_id,
               bit_count(phash_bits # B'{query_bits}') AS distance
        FROM images
        WHERE phash_bits IS NOT NULL
          AND id != :image_id
          AND bit_count(phash_bits # B'{query_bits}') <= :threshold
        ORDER BY distance ASC, id ASC
        OFFSET :offset LIMIT :limit
    """  # noqa: S608 — query_bits is validated to contain only 0/1 chars

    result = await db.execute(
        text(sql),
        {
            "image_id": image_id,
            "threshold": threshold,
            "offset": pagination.offset,
            "limit": pagination.limit,
        },
    )
    rows = result.fetchall()

    results = [
        SearchResult(
            image_id=row.id,
            filename=row.filename,
            s3_key=row.s3_key,
            score=1.0 - (row.distance / max_bits) if max_bits > 0 else 1.0,
            l1_group_id=row.l1_group_id,
            l2_cluster_id=None,
        )
        for row in rows
    ]

    return SearchResultsOut(query_image_id=image_id, results=results)


async def _do_similar_search(image_id: str, n_results: int, db: AsyncSession) -> SearchResultsOut:
    """Shared logic for similar search (POST and GET)."""
    query_image = await get_or_404(db, Image, image_id, "Query image not found")
    if not query_image.has_embedding:
        raise HTTPException(status_code=400, detail="Query image has no embedding yet")

    similar = await find_similar_images(db=db, image_id=image_id, n_results=n_results)
    return SearchResultsOut(query_image_id=image_id, results=similar)


@router.get(
    "/similar/{image_id}",
    response_model=SearchResultsOut,
    responses={
        400: {"model": ProblemDetail, "description": "Image has no embedding"},
        404: {"model": ProblemDetail, "description": "Query image not found"},
    },
)
@limiter.limit("30/minute")
async def search_similar_get(
    request: Request,
    image_id: str,
    n_results: int = Query(10, ge=1, le=100, description="Number of similar images to return (1-100)"),
    db: AsyncSession = Depends(get_db),
) -> SearchResultsOut:
    """GET alternative: find semantically similar images by image ID."""
    return await _do_similar_search(image_id, n_results, db)


@router.get(
    "/duplicates/{image_id}",
    response_model=SearchResultsOut,
    responses={
        400: {"model": ProblemDetail, "description": "Image has no perceptual hash"},
        404: {"model": ProblemDetail, "description": "Query image not found"},
    },
)
@limiter.limit("30/minute")
async def search_duplicates_get(
    request: Request,
    image_id: str,
    threshold: int | None = Query(
        None, ge=0, description="Hamming distance threshold for duplicate detection (default: config)"
    ),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> SearchResultsOut:
    """GET alternative: find near-duplicate images by image ID."""
    query_image = await get_or_404(db, Image, image_id, "Query image not found")
    if not query_image.phash:
        raise HTTPException(status_code=400, detail="Query image has no perceptual hash yet")

    effective_threshold = threshold if threshold is not None else settings.l1_hash_threshold

    return await _do_duplicate_search(
        db=db,
        image_id=image_id,
        phash=query_image.phash,
        threshold=effective_threshold,
        pagination=pagination,
    )
