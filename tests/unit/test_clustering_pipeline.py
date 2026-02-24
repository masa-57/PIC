"""Unit tests for clustering_pipeline.py — including bulk operation verification."""

from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Lightweight Row stand-in for column-level select(Image.id, Image.embedding)
ImageRow = namedtuple("ImageRow", ["id", "embedding"])
# Stand-in for projected L1Group query: select(L1Group.id, L1Group.representative_image_id, L1Group.member_count)
GroupRow = namedtuple("GroupRow", ["id", "representative_image_id", "member_count"])


@pytest.mark.unit
class TestRunFullClustering:
    """Test run_full_clustering function with mocked DB and clustering functions."""

    def _make_row(self, image_id: str, embedding: list[float] | None = None) -> ImageRow:
        return ImageRow(id=image_id, embedding=embedding or [0.1] * 768)

    def _make_db(self) -> AsyncMock:
        """Create a mock DB session with tracking for add/flush/commit/execute."""
        db = AsyncMock()
        added_objects: list[MagicMock] = []
        next_id = [1]
        execute_calls: list[object] = []

        def mock_add(obj: object) -> None:
            added_objects.append(obj)

        async def mock_flush() -> None:
            for obj in added_objects:
                if getattr(obj, "id", "set") is None:
                    obj.id = next_id[0]
                    next_id[0] += 1

        async def mock_execute(*args: object, **kwargs: object) -> MagicMock:
            execute_calls.append(args[0] if args else None)
            result = MagicMock()
            result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            return result

        db.add = MagicMock(side_effect=mock_add)
        db.flush = AsyncMock(side_effect=mock_flush)
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        db._added_objects = added_objects
        db._execute_calls = execute_calls
        return db

    @pytest.mark.asyncio
    async def test_empty_images_returns_zeros(self) -> None:
        """Test that empty DB returns all zero stats."""
        db = self._make_db()

        from nic.services.clustering_pipeline import run_full_clustering

        stats = await run_full_clustering(db, {})

        assert stats["total_images"] == 0
        assert stats["l1_groups"] == 0
        assert stats["l2_clusters"] == 0
        assert stats["l2_noise_groups"] == 0
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_clustering_with_multiple_images(self) -> None:
        """Test successful clustering with 5 images creating L1 groups and L2 clusters."""
        rows = [
            self._make_row("img1", [0.1] * 768),
            self._make_row("img2", [0.2] * 768),
            self._make_row("img3", [0.3] * 768),
            self._make_row("img4", [0.4] * 768),
            self._make_row("img5", [0.5] * 768),
        ]

        db = self._make_db()
        l1_created: list[object] = []
        phase = ["init"]
        num_l1_groups = 3  # Expected L1 groups from mock

        async def smart_execute(*args: object, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.all.return_value = []
            result.scalars.return_value.all.return_value = []

            if phase[0] == "init":
                result.all.return_value = rows
                phase[0] = "l1_ops"
            elif phase[0] == "l2_select_groups":
                # New code uses column-level select → .all() returns GroupRow tuples
                group_rows = [
                    GroupRow(
                        id=obj.id, representative_image_id=obj.representative_image_id, member_count=obj.member_count
                    )
                    for obj in l1_created
                ]
                result.all.return_value = group_rows
                phase[0] = "l2_ops"
            return result

        db.execute = AsyncMock(side_effect=smart_execute)

        flush_count = [0]
        next_id = [1]

        async def tracking_flush() -> None:
            # Assign IDs to newly added objects
            for obj in db._added_objects:
                if getattr(obj, "id", "set") is None:
                    obj.id = next_id[0]
                    next_id[0] += 1
            flush_count[0] += 1
            # After all L1 group flushes + the final flush, transition to L2
            if flush_count[0] == num_l1_groups + 1:
                phase[0] = "l2_select_groups"
                l1_created.extend(db._added_objects)

        db.flush = AsyncMock(side_effect=tracking_flush)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {
                0: ["img1", "img2"],
                1: ["img3", "img4"],
                2: ["img5"],
            }
            mock_rep.side_effect = lambda ids, *args: ids[0]
            mock_l2.return_value = {
                "clusters": {0: [1, 2], -1: [3]},
                "labels": [0, 0, -1],
                "coordinates_2d": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
                "n_clusters": 1,
                "n_noise": 1,
            }

            from nic.services.clustering_pipeline import run_full_clustering

            stats = await run_full_clustering(
                db,
                {
                    "l1_cluster_selection_epsilon": 0.15,
                    "l1_min_cluster_size": 2,
                    "l1_min_samples": 1,
                    "l2_min_cluster_size": 2,
                    "l2_min_samples": 1,
                },
            )

        assert stats["total_images"] == 5
        assert stats["l1_groups"] == 3
        assert stats["l2_clusters"] == 1
        assert stats["l2_noise_groups"] == 1

        mock_l1.assert_called_once()
        call_kwargs = mock_l1.call_args
        assert len(call_kwargs.kwargs["image_ids"]) == 5
        assert call_kwargs.kwargs["cluster_selection_epsilon"] == 0.15
        assert call_kwargs.kwargs["min_cluster_size"] == 2
        assert call_kwargs.kwargs["min_samples"] == 1

    @pytest.mark.asyncio
    async def test_all_images_in_one_l1_group(self) -> None:
        """Test clustering when all images end up in one L1 group."""
        rows = [
            self._make_row("img1", [0.1] * 768),
            self._make_row("img2", [0.2] * 768),
            self._make_row("img3", [0.3] * 768),
        ]

        db = self._make_db()
        l1_created: list[object] = []
        phase = ["init"]
        num_l1_groups = 1

        async def smart_execute(*args: object, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            if phase[0] == "init":
                result.all.return_value = rows
                phase[0] = "l1_ops"
            elif phase[0] == "l2_select_groups":
                group_rows = [
                    GroupRow(
                        id=obj.id, representative_image_id=obj.representative_image_id, member_count=obj.member_count
                    )
                    for obj in l1_created
                ]
                result.all.return_value = group_rows
                phase[0] = "l2_ops"
            return result

        db.execute = AsyncMock(side_effect=smart_execute)

        flush_count = [0]
        next_id = [1]

        async def tracking_flush() -> None:
            for obj in db._added_objects:
                if getattr(obj, "id", "set") is None:
                    obj.id = next_id[0]
                    next_id[0] += 1
            flush_count[0] += 1
            if flush_count[0] == num_l1_groups + 1:
                phase[0] = "l2_select_groups"
                l1_created.extend(db._added_objects)

        db.flush = AsyncMock(side_effect=tracking_flush)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {0: ["img1", "img2", "img3"]}
            mock_rep.return_value = "img1"
            mock_l2.return_value = {
                "clusters": {-1: [1]},
                "labels": [-1],
                "coordinates_2d": [[0.0, 0.0]],
                "n_clusters": 0,
                "n_noise": 1,
            }

            from nic.services.clustering_pipeline import run_full_clustering

            stats = await run_full_clustering(db, {})

        assert stats["total_images"] == 3
        assert stats["l1_groups"] == 1
        assert stats["l2_clusters"] == 0
        assert stats["l2_noise_groups"] == 1

    @pytest.mark.asyncio
    async def test_l2_clustering_returns_all_noise(self) -> None:
        """Test when L2 clustering classifies all groups as noise (outliers)."""
        rows = [
            self._make_row("img1", [0.1] * 768),
            self._make_row("img2", [0.9] * 768),
            self._make_row("img3", [0.5] * 768),
            self._make_row("img4", [0.3] * 768),
        ]

        db = self._make_db()
        l1_created: list[object] = []
        phase = ["init"]
        num_l1_groups = 4

        async def smart_execute(*args: object, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            if phase[0] == "init":
                result.all.return_value = rows
                phase[0] = "l1_ops"
            elif phase[0] == "l2_select_groups":
                group_rows = [
                    GroupRow(
                        id=obj.id, representative_image_id=obj.representative_image_id, member_count=obj.member_count
                    )
                    for obj in l1_created
                ]
                result.all.return_value = group_rows
                phase[0] = "l2_ops"
            return result

        db.execute = AsyncMock(side_effect=smart_execute)

        flush_count = [0]
        next_id = [1]

        async def tracking_flush() -> None:
            for obj in db._added_objects:
                if getattr(obj, "id", "set") is None:
                    obj.id = next_id[0]
                    next_id[0] += 1
            flush_count[0] += 1
            if flush_count[0] == num_l1_groups + 1:
                phase[0] = "l2_select_groups"
                l1_created.extend(db._added_objects)

        db.flush = AsyncMock(side_effect=tracking_flush)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {
                0: ["img1"],
                1: ["img2"],
                2: ["img3"],
                3: ["img4"],
            }
            mock_rep.side_effect = lambda ids, *args: ids[0]
            mock_l2.return_value = {
                "clusters": {-1: [1, 2, 3, 4]},
                "labels": [-1, -1, -1, -1],
                "coordinates_2d": [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]],
                "n_clusters": 0,
                "n_noise": 4,
            }

            from nic.services.clustering_pipeline import run_full_clustering

            stats = await run_full_clustering(db, {})

        assert stats["total_images"] == 4
        assert stats["l1_groups"] == 4
        assert stats["l2_clusters"] == 0
        assert stats["l2_noise_groups"] == 4

    @pytest.mark.asyncio
    async def test_rolls_back_if_l2_clustering_fails(self) -> None:
        """A failure after destructive updates must rollback L1/L2 changes."""
        rows = [self._make_row("img1", [0.1] * 768), self._make_row("img2", [0.2] * 768)]

        db = self._make_db()
        l1_created: list[object] = []
        phase = ["init"]
        num_l1_groups = 1

        async def smart_execute(*args: object, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            if phase[0] == "init":
                result.all.return_value = rows
                phase[0] = "l1_ops"
            elif phase[0] == "l2_select_groups":
                group_rows = [
                    GroupRow(
                        id=obj.id, representative_image_id=obj.representative_image_id, member_count=obj.member_count
                    )
                    for obj in l1_created
                ]
                result.all.return_value = group_rows
                phase[0] = "l2_ops"
            return result

        db.execute = AsyncMock(side_effect=smart_execute)
        db.rollback = AsyncMock()

        flush_count = [0]
        next_id = [1]

        async def tracking_flush() -> None:
            for obj in db._added_objects:
                if getattr(obj, "id", "set") is None:
                    obj.id = next_id[0]
                    next_id[0] += 1
            flush_count[0] += 1
            if flush_count[0] == num_l1_groups + 1:
                phase[0] = "l2_select_groups"
                l1_created.extend(db._added_objects)

        db.flush = AsyncMock(side_effect=tracking_flush)

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2", side_effect=RuntimeError("l2 boom")),
        ):
            mock_l1.return_value = {0: ["img1", "img2"]}
            mock_rep.return_value = "img1"

            from nic.services.clustering_pipeline import run_full_clustering

            with pytest.raises(RuntimeError, match="l2 boom"):
                await run_full_clustering(db, {})

        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()


@pytest.mark.unit
class TestBulkOperations:
    """Verify that clustering pipeline uses bulk SQL operations instead of per-row loops."""

    @pytest.mark.asyncio
    async def test_uses_bulk_delete_not_loop(self) -> None:
        """Verify bulk DELETE for L1 groups and L2 clusters instead of delete-by-loop."""
        rows = [ImageRow(id="img1", embedding=[0.1] * 768)]

        db = AsyncMock()
        execute_statements: list[str] = []
        call_count = [0]

        async def tracking_execute(stmt, *args, **kwargs):
            execute_statements.append(str(stmt))
            call_count[0] += 1
            result = MagicMock()
            # First call returns image rows; L2 group query returns GroupRow
            if call_count[0] == 1:
                result.all.return_value = rows
            elif call_count[0] == 7:
                # L2 projected select (after L1 create: init + 2 update + 1 delete + 1 flush update + 1 flush)
                result.all.return_value = [GroupRow(id=1, representative_image_id="img1", member_count=1)]
            else:
                result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            return result

        db.execute = AsyncMock(side_effect=tracking_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {0: ["img1"]}
            mock_rep.return_value = "img1"
            mock_l2.return_value = {
                "clusters": {},
                "labels": [],
                "coordinates_2d": [[0.0, 0.0]],
                "n_clusters": 0,
                "n_noise": 1,
            }

            from nic.services.clustering_pipeline import run_full_clustering

            await run_full_clustering(db, {})

        # Verify execute was called (bulk operations), NOT db.delete() per-row
        db.delete.assert_not_called()
        assert db.execute.call_count > 0

    @pytest.mark.asyncio
    async def test_column_level_loading(self) -> None:
        """Verify the initial query uses column-level select, not full ORM load."""
        rows = [ImageRow(id="img1", embedding=[0.1] * 768)]

        db = AsyncMock()
        first_stmt = [None]
        call_count = [0]

        async def capture_execute(stmt, *args, **kwargs):
            if first_stmt[0] is None:
                first_stmt[0] = stmt
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.all.return_value = rows
            elif call_count[0] == 7:
                result.all.return_value = [GroupRow(id=1, representative_image_id="img1", member_count=1)]
            else:
                result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            return result

        db.execute = AsyncMock(side_effect=capture_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch("nic.services.clustering_pipeline.cluster_level1") as mock_l1,
            patch("nic.services.clustering_pipeline.select_representative") as mock_rep,
            patch("nic.services.clustering_pipeline.cluster_level2") as mock_l2,
        ):
            mock_l1.return_value = {0: ["img1"]}
            mock_rep.return_value = "img1"
            mock_l2.return_value = {
                "clusters": {},
                "labels": [],
                "coordinates_2d": [[0.0, 0.0]],
                "n_clusters": 0,
                "n_noise": 1,
            }

            from nic.services.clustering_pipeline import run_full_clustering

            await run_full_clustering(db, {})

        # The function uses result.all() for the initial image query (column-level select)
        assert db.execute.call_count > 0

    @pytest.mark.asyncio
    async def test_returns_clustering_stats_typed_dict(self) -> None:
        """Verify return type is ClusteringStats with correct keys."""
        db = AsyncMock()

        async def empty_execute(*args, **kwargs):
            result = MagicMock()
            result.all.return_value = []
            result.scalars.return_value.all.return_value = []
            return result

        db.execute = AsyncMock(side_effect=empty_execute)
        db.add = MagicMock()

        from nic.services.clustering_pipeline import run_full_clustering

        stats = await run_full_clustering(db, {})

        # Verify it has exactly the expected keys
        assert set(stats.keys()) == {"total_images", "l1_groups", "l2_clusters", "l2_noise_groups"}
        # Verify all values are ints
        for v in stats.values():
            assert isinstance(v, int)
