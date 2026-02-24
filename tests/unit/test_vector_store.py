"""Unit tests for the vector store service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestFindSimilarImages:
    @pytest.mark.asyncio
    async def test_returns_empty_for_missing_image(self):
        """If the query image doesn't exist, return empty results."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        # First call: SET LOCAL hnsw.ef_search, second: query image lookup
        mock_session.execute = AsyncMock(side_effect=[MagicMock(), mock_result])

        from nic.services.vector_store import find_similar_images

        results = await find_similar_images(mock_session, "nonexistent-id")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_image_without_embedding(self):
        """If the query image has no embedding, return empty results."""
        mock_image = MagicMock()
        mock_image.embedding = None

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_image
        # First call: SET LOCAL hnsw.ef_search, second: query image lookup
        mock_session.execute = AsyncMock(side_effect=[MagicMock(), mock_result])

        from nic.services.vector_store import find_similar_images

        results = await find_similar_images(mock_session, "img-no-embed")
        assert results == []

    @pytest.mark.asyncio
    async def test_returns_similar_images(self):
        """Should return images sorted by similarity score."""
        query_image = MagicMock()
        query_image.id = "query-1"
        query_image.embedding = [1.0] * 768

        # Simulate two similar results
        img1 = MagicMock()
        img1.id = "similar-1"
        img1.filename = "cake1.jpg"
        img1.s3_key = "processed/cake1.jpg"
        img1.l1_group_id = 1
        img1.l1_group = MagicMock()
        img1.l1_group.l2_cluster_id = 5

        img2 = MagicMock()
        img2.id = "similar-2"
        img2.filename = "cake2.jpg"
        img2.s3_key = "processed/cake2.jpg"
        img2.l1_group_id = 2
        img2.l1_group = None

        mock_session = AsyncMock()

        # First call: SET LOCAL hnsw.ef_search
        # Second call: query image lookup
        # Third call: search results
        mock_query_result = MagicMock()
        mock_query_result.scalar_one_or_none.return_value = query_image

        mock_search_result = MagicMock()
        mock_search_result.all.return_value = [(img1, 0.1), (img2, 0.3)]

        mock_session.execute = AsyncMock(side_effect=[MagicMock(), mock_query_result, mock_search_result])

        from nic.services.vector_store import find_similar_images

        results = await find_similar_images(mock_session, "query-1", n_results=5)
        assert len(results) == 2
        assert results[0].image_id == "similar-1"
        assert results[0].score == pytest.approx(0.9)  # 1.0 - 0.1
        assert results[0].l2_cluster_id == 5
        assert results[1].image_id == "similar-2"
        assert results[1].score == pytest.approx(0.7)  # 1.0 - 0.3
        assert results[1].l2_cluster_id is None

    @pytest.mark.asyncio
    async def test_uses_configured_ef_search(self):
        """find_similar_images should use settings.hnsw_ef_search value."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(side_effect=[MagicMock(), mock_result])

        with patch("nic.services.vector_store.settings") as mock_settings:
            mock_settings.hnsw_ef_search = 200
            from nic.services.vector_store import find_similar_images

            await find_similar_images(mock_session, "test-id")

        # Verify the SET LOCAL call used the configured value
        first_call_args = mock_session.execute.call_args_list[0]
        sql_text = str(first_call_args[0][0])
        assert "200" in sql_text
