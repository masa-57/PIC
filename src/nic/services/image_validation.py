"""Shared image safety checks."""

from PIL import Image as PILImage

MAX_IMAGE_PIXELS = 50_000_000
PILImage.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def validate_pixel_count(image: PILImage.Image) -> None:
    """Reject images exceeding the configured pixel bound."""
    width, height = image.size
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(f"Image exceeds maximum pixel count ({MAX_IMAGE_PIXELS})")
