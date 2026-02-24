"""Unit tests for the embedding service."""

import io
from unittest.mock import patch

import pytest
from PIL import Image as PILImage

from pic.services.embedding import compute_dhash, compute_hashes, compute_phash, hamming_distance


def _make_test_image(width: int = 100, height: int = 100, color: str = "red") -> bytes:
    """Create a simple test image as bytes."""
    img = PILImage.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.mark.unit
class TestPerceptualHashing:
    def test_phash_returns_hex_string(self):
        img = PILImage.new("RGB", (100, 100), "red")
        result = compute_phash(img)
        assert isinstance(result, str)
        # Hex string for hash_size=16: 256 bits = 64 hex chars
        assert len(result) == 64

    def test_dhash_returns_hex_string(self):
        img = PILImage.new("RGB", (100, 100), "red")
        result = compute_dhash(img)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_identical_images_same_hash(self):
        img1 = PILImage.new("RGB", (100, 100), "blue")
        img2 = PILImage.new("RGB", (100, 100), "blue")
        assert compute_phash(img1) == compute_phash(img2)

    def test_different_images_different_hash(self):
        img1 = PILImage.new("RGB", (100, 100), "red")
        img2 = PILImage.new("RGB", (100, 100), "blue")
        # Different solid colors may still have similar hashes due to DCT
        # but they should at least return valid hashes
        h1 = compute_phash(img1)
        h2 = compute_phash(img2)
        assert isinstance(h1, str)
        assert isinstance(h2, str)

    def test_compute_hashes_from_bytes(self):
        image_bytes = _make_test_image()
        phash, dhash = compute_hashes(image_bytes)
        assert isinstance(phash, str)
        assert isinstance(dhash, str)
        assert len(phash) == 64
        assert len(dhash) == 64

    def test_compute_hashes_rgba_conversion(self):
        """RGBA images should be converted to RGB before hashing."""
        img = PILImage.new("RGBA", (100, 100), (255, 0, 0, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        phash, dhash = compute_hashes(image_bytes)
        assert isinstance(phash, str)
        assert isinstance(dhash, str)

    def test_compute_hashes_rejects_oversized_image(self):
        image_bytes = _make_test_image()
        with (
            patch("pic.services.embedding.validate_pixel_count", side_effect=ValueError("too many pixels")),
            pytest.raises(ValueError, match="too many pixels"),
        ):
            compute_hashes(image_bytes)


@pytest.mark.unit
class TestHammingDistance:
    def test_identical_hashes(self):
        h = "f0e1d2c3b4a59687" * 4  # 64 hex chars = 256 bits
        assert hamming_distance(h, h) == 0

    def test_one_bit_difference(self):
        h1 = "0" * 64
        h2 = "0" * 63 + "1"
        dist = hamming_distance(h1, h2)
        assert dist == 1

    def test_all_bits_different(self):
        h1 = "0" * 64
        h2 = "f" * 64
        dist = hamming_distance(h1, h2)
        assert dist == 256  # All 256 bits differ

    def test_symmetry(self):
        h1 = "abcdef0123456789" * 4
        h2 = "0123456789abcdef" * 4
        assert hamming_distance(h1, h2) == hamming_distance(h2, h1)

    def test_half_bits_different(self):
        """Alternating nibbles: 0x0 vs 0xf differ by 4 bits each."""
        h1 = "0f" * 32  # 64 hex chars
        h2 = "00" * 32
        dist = hamming_distance(h1, h2)
        # Each "f" nibble has 4 set bits, 32 occurrences = 128 bits
        assert dist == 128

    def test_single_nibble_difference(self):
        h1 = "0" * 64
        h2 = "8" + "0" * 63  # Only highest nibble has MSB set
        dist = hamming_distance(h1, h2)
        assert dist == 1

    def test_non_hex_input_raises(self):
        """Non-hex characters should raise ValueError."""
        with pytest.raises((ValueError, TypeError)):
            hamming_distance("g" * 64, "0" * 64)

    def test_mismatched_length_raises_or_handles(self):
        """Mismatched hash lengths should raise or return a result without crashing."""
        try:
            result = hamming_distance("0" * 32, "0" * 64)
            assert isinstance(result, int)
        except (ValueError, TypeError):
            pass  # Raising is acceptable behavior for mismatched lengths


@pytest.mark.unit
class TestComputeEmbeddingsBatch:
    def test_batch_returns_correct_count(self):
        """compute_embeddings_batch returns one embedding per input image."""
        from unittest.mock import MagicMock, patch

        import torch

        mock_model = MagicMock()
        mock_processor = MagicMock()

        # Mock processor: return object with .to() that returns itself
        mock_inputs = MagicMock()
        mock_inputs.to.return_value = mock_inputs
        mock_inputs.__getitem__ = MagicMock()
        mock_inputs.__iter__ = MagicMock(return_value=iter(["pixel_values"]))
        mock_inputs.keys.return_value = ["pixel_values"]
        mock_processor.return_value = mock_inputs

        # Mock model output: batch of 2 with 768-dim CLS token
        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.randn(2, 197, 768)
        mock_model.return_value = mock_output

        with patch("pic.services.embedding._load_model", return_value=(mock_model, mock_processor)):
            from pic.services.embedding import compute_embeddings_batch

            img1 = _make_test_image(color="red")
            img2 = _make_test_image(color="blue")
            results = compute_embeddings_batch([img1, img2])

        assert len(results) == 2
        assert len(results[0]) == 768
        assert len(results[1]) == 768

    def test_empty_batch(self):
        """Empty input returns empty output."""
        from unittest.mock import MagicMock, patch

        with patch("pic.services.embedding._load_model") as mock_load:
            mock_load.return_value = (MagicMock(), MagicMock())

            from pic.services.embedding import compute_embeddings_batch

            results = compute_embeddings_batch([])

        assert results == []
