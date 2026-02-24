import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pic.config import settings
from pic.models.db import Image
from pic.models.schemas import SearchResult

logger = logging.getLogger(__name__)


async def ensure_pgvector_extension(db: AsyncSession) -> None:
    """Create the pgvector extension if it doesn't exist."""
    await db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await db.commit()


async def find_similar_images(
    db: AsyncSession,
    image_id: str,
    n_results: int = 20,
) -> list[SearchResult]:
    """Find similar images using pgvector cosine distance (k-NN)."""
    # Tune HNSW ef_search for recall/speed trade-off (default 40; higher = better recall)
    ef_search = max(1, min(int(settings.hnsw_ef_search), 1000))
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))  # noqa: S608 - ef_search is clamped int

    # Get the query image embedding
    query_result = await db.execute(select(Image).where(Image.id == image_id))
    query_image = query_result.scalar_one_or_none()
    if not query_image or query_image.embedding is None:
        return []

    # pgvector cosine distance: <=> operator
    # Lower distance = more similar. Cosine distance = 1 - cosine_similarity
    stmt = (
        select(
            Image,
            Image.embedding.cosine_distance(query_image.embedding).label("distance"),
        )
        .where(Image.id != image_id, Image.embedding.isnot(None))
        .order_by("distance")
        .limit(n_results)
        .options(selectinload(Image.l1_group))
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        SearchResult(
            image_id=img.id,
            filename=img.filename,
            s3_key=img.s3_key,
            score=1.0 - distance,  # Convert distance to similarity
            l1_group_id=img.l1_group_id,
            l2_cluster_id=img.l1_group.l2_cluster_id if img.l1_group else None,
        )
        for img, distance in rows
    ]


async def get_all_embeddings(db: AsyncSession) -> tuple[list[str], list[list[float]]]:
    """Retrieve all image IDs and their embeddings. Used for clustering."""
    result = await db.execute(select(Image.id, Image.embedding).where(Image.embedding.isnot(None)))
    rows = result.all()
    ids = [row[0] for row in rows]
    embeddings = [list(row[1]) for row in rows]
    return ids, embeddings
