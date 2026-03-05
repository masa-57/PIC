"""Unit tests for the image store service."""

import io
from unittest.mock import patch

import pytest
from PIL import Image as PILImage

from pic.services.image_store import (
    _clear_presigned_url_cache,
    generate_presigned_url,
    generate_thumbnail,
    get_image_dimensions,
)


def _make_test_image(width: int = 800, height: int = 600, color: str = "green") -> bytes:
    """Create a test image as bytes."""
    img = PILImage.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.mark.unit
class TestThumbnailGeneration:
    def test_generates_smaller_image(self):
        image_bytes = _make_test_image(800, 600)
        thumbnail_bytes = generate_thumbnail(image_bytes)

        thumb = PILImage.open(io.BytesIO(thumbnail_bytes))
        assert thumb.width <= 256
        assert thumb.height <= 256

    def test_maintains_aspect_ratio(self):
        # 800x400 → should become 256x128 (2:1 ratio)
        image_bytes = _make_test_image(800, 400)
        thumbnail_bytes = generate_thumbnail(image_bytes)

        thumb = PILImage.open(io.BytesIO(thumbnail_bytes))
        ratio = thumb.width / thumb.height
        assert abs(ratio - 2.0) < 0.1

    def test_handles_rgba(self):
        """RGBA images should be converted to RGB for JPEG thumbnail."""
        img = PILImage.new("RGBA", (400, 400), (255, 0, 0, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        thumbnail_bytes = generate_thumbnail(image_bytes)
        thumb = PILImage.open(io.BytesIO(thumbnail_bytes))
        assert thumb.mode == "RGB"

    def test_output_is_jpeg(self):
        image_bytes = _make_test_image()
        thumbnail_bytes = generate_thumbnail(image_bytes)

        thumb = PILImage.open(io.BytesIO(thumbnail_bytes))
        assert thumb.format == "JPEG"

    def test_small_image_not_upscaled(self):
        """Images smaller than thumbnail size should not be upscaled."""
        image_bytes = _make_test_image(100, 100)
        thumbnail_bytes = generate_thumbnail(image_bytes)

        thumb = PILImage.open(io.BytesIO(thumbnail_bytes))
        assert thumb.width <= 100
        assert thumb.height <= 100

    def test_rejects_oversized_image(self):
        image_bytes = _make_test_image(100, 100)
        with (
            patch("pic.services.image_store.validate_pixel_count", side_effect=ValueError("too many pixels")),
            pytest.raises(ValueError, match="too many pixels"),
        ):
            generate_thumbnail(image_bytes)


@pytest.mark.unit
class TestImageDimensions:
    def test_returns_correct_dimensions(self):
        image_bytes = _make_test_image(800, 600)
        w, h = get_image_dimensions(image_bytes)
        assert w == 800
        assert h == 600

    def test_square_image(self):
        image_bytes = _make_test_image(512, 512)
        w, h = get_image_dimensions(image_bytes)
        assert w == 512
        assert h == 512

    def test_invalid_image_bytes_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid or unsupported image bytes"):
            get_image_dimensions(b"not-an-image")

    def test_rejects_oversized_image(self):
        image_bytes = _make_test_image(100, 100)
        with (
            patch("pic.services.image_store.validate_pixel_count", side_effect=ValueError("too many pixels")),
            pytest.raises(ValueError, match="too many pixels"),
        ):
            get_image_dimensions(image_bytes)


@pytest.mark.unit
class TestMoveS3Object:
    def test_delegates_to_backend(self, mock_s3):
        from pic.services.image_store import move_s3_object

        move_s3_object("images/photo.jpg", "processed/photo.jpg")

        mock_s3.move.assert_called_once_with("images/photo.jpg", "processed/photo.jpg")


@pytest.mark.unit
class TestPresignedUrl:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        _clear_presigned_url_cache()
        yield
        _clear_presigned_url_cache()

    def test_clamps_negative_expiry(self, mock_s3):
        mock_s3.get_url.return_value = "https://example.com/signed"
        generate_presigned_url("processed/photo.jpg", expires_in=-30)
        mock_s3.get_url.assert_called_once_with("processed/photo.jpg", expires_in=1)

    def test_clamps_huge_expiry(self, mock_s3):
        from pic.config import settings

        mock_s3.get_url.return_value = "https://example.com/signed"
        generate_presigned_url("processed/photo.jpg", expires_in=settings.presigned_url_max_expiry + 9999)
        mock_s3.get_url.assert_called_once_with(
            "processed/photo.jpg", expires_in=settings.presigned_url_max_expiry
        )

    def test_reuses_cached_url_before_ttl_expiry(self, mock_s3):
        mock_s3.get_url.return_value = "https://example.com/signed-1"
        first = generate_presigned_url("processed/photo.jpg", expires_in=120)

        # Should return cache hit, not call signer again.
        mock_s3.get_url.return_value = "https://example.com/signed-2"
        second = generate_presigned_url("processed/photo.jpg", expires_in=120)

        assert first == "https://example.com/signed-1"
        assert second == "https://example.com/signed-1"
        assert mock_s3.get_url.call_count == 1

    def test_regenerates_url_after_ttl_window(self, mock_s3):
        mock_s3.get_url.side_effect = [
            "https://example.com/signed-1",
            "https://example.com/signed-2",
        ]

        # Cache logic now reads time twice on misses: before and after URL generation.
        with patch("pic.services.image_store.time.monotonic", side_effect=[0.0, 0.0, 61.0, 61.0]):
            first = generate_presigned_url("processed/photo.jpg", expires_in=120)
            second = generate_presigned_url("processed/photo.jpg", expires_in=120)

        assert first == "https://example.com/signed-1"
        assert second == "https://example.com/signed-2"
        assert mock_s3.get_url.call_count == 2
