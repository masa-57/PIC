import io
import logging
import threading
from typing import Any

import imagehash
import torch
from PIL import Image as PILImage
from transformers import AutoImageProcessor, AutoModel

from pic.config import settings
from pic.services.image_validation import validate_pixel_count

logger = logging.getLogger(__name__)

# Module-level cache for the model
_model = None
_processor = None
_model_lock = threading.Lock()


def _get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model() -> tuple[Any, Any]:
    global _model, _processor
    if _model is None:
        with _model_lock:
            if _model is None:
                device = _get_device()
                logger.info("Loading DINOv2 model %s on %s", settings.dinov2_model, device)
                _processor = AutoImageProcessor.from_pretrained(settings.dinov2_model)  # type: ignore[no-untyped-call]
                _model = AutoModel.from_pretrained(settings.dinov2_model).to(device)
                _model.eval()
                logger.info("DINOv2 model loaded")
    return _model, _processor


def compute_phash(image: PILImage.Image) -> str:
    """Compute perceptual hash. Returns hex string."""
    return str(imagehash.phash(image, hash_size=settings.phash_size))


def compute_dhash(image: PILImage.Image) -> str:
    """Compute difference hash. Returns hex string."""
    return str(imagehash.dhash(image, hash_size=settings.phash_size))


def compute_hashes(image_bytes_or_pil: bytes | PILImage.Image) -> tuple[str, str]:
    """Compute both pHash and dHash for an image. Returns (phash, dhash).

    Accepts either raw bytes or an already-opened PIL Image to avoid redundant opens.
    """
    if isinstance(image_bytes_or_pil, PILImage.Image):
        image = image_bytes_or_pil
        validate_pixel_count(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        return compute_phash(image), compute_dhash(image)
    with PILImage.open(io.BytesIO(image_bytes_or_pil)) as image:
        validate_pixel_count(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        return compute_phash(image), compute_dhash(image)


@torch.no_grad()
def compute_embedding(image_bytes: bytes) -> list[float]:
    """Compute DINOv2 embedding for a single image. Returns 768-dim vector."""
    model, processor = _load_model()
    device = _get_device()

    with PILImage.open(io.BytesIO(image_bytes)) as image:
        validate_pixel_count(image)
        if image.mode != "RGB":
            image = image.convert("RGB")  # type: ignore[assignment]
        inputs = processor(images=image, return_tensors="pt").to(device)

    outputs = model(**inputs)
    # CLS token embedding
    embedding = outputs.last_hidden_state[:, 0, :]
    # L2 normalize
    embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)
    return list(embedding.squeeze().cpu().tolist())


@torch.no_grad()
def compute_embeddings_batch(images_bytes: list[bytes]) -> list[list[float]]:
    """Compute DINOv2 embeddings for a batch of images. Returns list of 768-dim vectors."""
    model, processor = _load_model()
    device = _get_device()

    all_embeddings: list[list[float]] = []

    for i in range(0, len(images_bytes), settings.embedding_batch_size):
        batch_bytes = images_bytes[i : i + settings.embedding_batch_size]
        images: list[PILImage.Image] = []
        try:
            for img_bytes in batch_bytes:
                img: PILImage.Image = PILImage.open(io.BytesIO(img_bytes))
                try:
                    validate_pixel_count(img)
                    if img.mode != "RGB":
                        converted = img.convert("RGB")
                        img.close()
                        img = converted
                    images.append(img)
                except Exception:
                    img.close()
                    raise

            inputs = processor(images=images, return_tensors="pt", padding=True).to(device)
        finally:
            for img in images:
                img.close()
            del images

        outputs = model(**inputs)
        embeddings = outputs.last_hidden_state[:, 0, :]
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        all_embeddings.extend(embeddings.cpu().tolist())

        del inputs, outputs, embeddings
        if device == "cuda":
            torch.cuda.empty_cache()

        logger.info("Embedded batch %d-%d of %d", i, i + len(batch_bytes), len(images_bytes))

    return all_embeddings


def hamming_distance(hash1: str, hash2: str) -> int:
    """Compute Hamming distance between two hex-encoded hashes."""
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    return h1 - h2


from pic.services.hash_utils import hex_to_bitstring as hex_to_bitstring  # noqa: F401, E402
