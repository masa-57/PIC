"""Integration tests for pipeline discovery against real PostgreSQL (#128)."""

import uuid
from unittest.mock import patch

import pytest

from pic.models.db import Image
from pic.worker.pipeline_discover import phase_discover_and_dedup


def _image(s3_key: str, has_embedding: int) -> Image:
    return Image(
        id=str(uuid.uuid4()),
        filename=s3_key.rsplit("/", 1)[-1],
        s3_key=s3_key,
        embedding=[0.0] * 768 if has_embedding else None,
        has_embedding=has_embedding,
    )


@pytest.mark.integration
class TestDiscoverExistingRows:
    async def test_queues_url_ingested_row_and_rejects_processed_duplicate(self, db):
        pending = _image("images/abc_url.jpg", has_embedding=0)  # written by URL ingest
        done = _image("processed/done.jpg", has_embedding=1)
        db.add_all([pending, done])
        await db.commit()

        with (
            patch(
                "pic.worker.pipeline_discover.list_s3_objects",
                return_value=["images/abc_url.jpg", "images/done.jpg"],
            ),
            patch("pic.worker.pipeline_discover.move_s3_object") as mock_move,
        ):
            new_ids, stats = await phase_discover_and_dedup(db, "job-1")

        assert new_ids == [pending.id]
        assert stats == {"discovered": 2, "duplicates": 1}
        mock_move.assert_called_once_with("images/done.jpg", "rejected/done.jpg")
