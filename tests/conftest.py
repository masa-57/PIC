from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_embedding() -> list[float]:
    """A fixed 768-dim embedding vector for testing."""
    import numpy as np

    rng = np.random.default_rng(42)
    vec = rng.standard_normal(768).astype(float)
    vec = vec / np.linalg.norm(vec)  # L2 normalize
    return vec.tolist()


@pytest.fixture
def sample_phash() -> str:
    """A fixed 64-char (256-bit) perceptual hash for testing."""
    return "f0e1d2c3b4a59687f0e1d2c3b4a59687f0e1d2c3b4a59687f0e1d2c3b4a59687"


@pytest.fixture
def sample_phash_alt() -> str:
    """A different 64-char perceptual hash for tests needing distinct images."""
    return "1a2b3c4d5e6f7890" * 4


@pytest.fixture
def mock_s3():
    """Mock storage backend."""
    mock_backend = MagicMock()
    with patch("pic.services.image_store.get_storage_backend", return_value=mock_backend):
        yield mock_backend
