"""Unit tests for image safety validation helpers."""

from unittest.mock import MagicMock

import pytest
from PIL import Image as PILImage

from pic.services.image_validation import MAX_IMAGE_PIXELS, validate_pixel_count


@pytest.mark.unit
def test_validate_pixel_count_accepts_small_image() -> None:
    image = MagicMock()
    image.size = (1000, 1000)
    validate_pixel_count(image)


@pytest.mark.unit
def test_validate_pixel_count_rejects_large_image() -> None:
    image = MagicMock()
    image.size = (10000, 6000)  # 60M pixels
    with pytest.raises(ValueError, match="maximum pixel count"):
        validate_pixel_count(image)


@pytest.mark.unit
def test_pillow_max_pixels_is_configured() -> None:
    assert PILImage.MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS
