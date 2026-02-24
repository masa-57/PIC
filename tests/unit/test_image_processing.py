"""Unit tests for worker.image_processing helpers."""

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image as PILImage

from pic.worker.image_processing import (
    check_content_duplicate,
    compute_content_hash,
    insert_image_record,
    process_single_image,
    retry_single_image_ingest,
    safe_filename,
)


def _image_bytes() -> bytes:
    img = PILImage.new("RGB", (64, 64), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_compute_content_hash_is_deterministic() -> None:
    payload = b"image-data"
    assert compute_content_hash(payload) == compute_content_hash(payload)


def test_safe_filename_sanitizes_and_has_fallback() -> None:
    assert safe_filename("../unsafe/name.jpg", "abc12345") == "name.jpg"
    assert safe_filename("", "abc12345").startswith("unnamed_abc12345")


def test_process_single_image_success_sets_fields_and_moves_key() -> None:
    img = SimpleNamespace(id="img-1", s3_key="images/img-1.jpg")

    with (
        patch("pic.worker.image_processing.compute_hashes", return_value=("phash", "dhash")),
        patch("pic.worker.image_processing.hex_to_bitstring", return_value="bits"),
        patch("pic.worker.image_processing.get_image_dimensions", return_value=(64, 64)),
        patch("pic.worker.image_processing.generate_thumbnail", return_value=b"thumb"),
        patch("pic.worker.image_processing.upload_to_s3") as mock_upload,
        patch("pic.worker.image_processing.move_s3_object") as mock_move,
    ):
        ok = process_single_image(img, _image_bytes(), [0.1] * 4)

    assert ok is True
    assert img.phash == "phash"
    assert img.dhash == "dhash"
    assert img.phash_bits == "bits"
    assert img.has_embedding == 1
    assert img.s3_thumbnail_key == "thumbnails/img-1.jpg"
    assert img.s3_key == "processed/img-1.jpg"
    mock_upload.assert_called_once()
    mock_move.assert_called_once_with("images/img-1.jpg", "processed/img-1.jpg")


def test_process_single_image_keeps_original_key_if_move_fails() -> None:
    img = SimpleNamespace(id="img-1", s3_key="images/img-1.jpg")

    with (
        patch("pic.worker.image_processing.compute_hashes", return_value=("phash", "dhash")),
        patch("pic.worker.image_processing.hex_to_bitstring", return_value="bits"),
        patch("pic.worker.image_processing.get_image_dimensions", return_value=(64, 64)),
        patch("pic.worker.image_processing.generate_thumbnail", return_value=b"thumb"),
        patch("pic.worker.image_processing.upload_to_s3"),
        patch("pic.worker.image_processing.move_s3_object", side_effect=RuntimeError("boom")),
    ):
        ok = process_single_image(img, _image_bytes(), [0.1] * 4)

    assert ok is True
    assert img.s3_key == "images/img-1.jpg"


def test_process_single_image_returns_false_on_decode_error() -> None:
    img = SimpleNamespace(id="img-1", s3_key="images/img-1.jpg")
    with patch("pic.worker.image_processing.PILImage.open", side_effect=OSError("bad image")):
        assert process_single_image(img, b"not-an-image", [0.1]) is False


def test_retry_single_image_ingest_succeeds_on_second_attempt() -> None:
    img = SimpleNamespace(id="img-1")
    with (
        patch(
            "pic.worker.image_processing.compute_embeddings_batch",
            side_effect=[RuntimeError("first"), [[0.2] * 4]],
        ),
        patch("pic.worker.image_processing.process_single_image", return_value=True) as mock_process,
    ):
        assert retry_single_image_ingest(img, b"image-bytes") is True

    mock_process.assert_called_once()


def test_retry_single_image_ingest_returns_false_after_exhaustion() -> None:
    img = SimpleNamespace(id="img-1")
    with (
        patch("pic.worker.image_processing.compute_embeddings_batch", side_effect=RuntimeError("always")),
        patch("pic.worker.image_processing.process_single_image") as mock_process,
    ):
        assert retry_single_image_ingest(img, b"image-bytes") is False

    mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_check_content_duplicate_true_and_false() -> None:
    db = AsyncMock()
    present = MagicMock()
    present.scalar_one_or_none.return_value = "existing-id"
    db.execute = AsyncMock(return_value=present)
    assert await check_content_duplicate(db, "hash") is True

    missing = MagicMock()
    missing.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=missing)
    assert await check_content_duplicate(db, "hash") is False


@pytest.mark.asyncio
async def test_insert_image_record_returns_id_when_inserted() -> None:
    db = AsyncMock()
    inserted = MagicMock()
    inserted.rowcount = 1
    db.execute = AsyncMock(return_value=inserted)

    with patch("pic.worker.image_processing.uuid.uuid4", return_value="fixed-uuid"):
        image_id = await insert_image_record(
            db,
            filename="a.jpg",
            s3_key="images/a.jpg",
            content_hash="hash",
            file_size=1,
        )

    assert image_id == "fixed-uuid"


@pytest.mark.asyncio
async def test_insert_image_record_returns_none_on_conflict() -> None:
    db = AsyncMock()
    conflict = MagicMock()
    conflict.rowcount = 0
    db.execute = AsyncMock(return_value=conflict)

    image_id = await insert_image_record(
        db,
        filename="a.jpg",
        s3_key="images/a.jpg",
        content_hash="hash",
        file_size=1,
    )
    assert image_id is None
