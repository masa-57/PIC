"""Shared constants used across multiple modules."""

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Image file extensions accepted for processing
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"})

# PostgreSQL advisory lock ID — shared across pipeline, clustering, and gdrive-sync
# workers to ensure mutual exclusion. All three use the same lock because they
# all modify the same data (images + clusters).
ADVISORY_LOCK_ID: int = 0x4E494301  # "PIC\x01"

# S3 key prefixes for image lifecycle
S3_PREFIX_INBOX: str = "images/"
S3_PREFIX_PROCESSED: str = "processed/"
S3_PREFIX_REJECTED: str = "rejected/"
S3_PREFIX_THUMBNAILS: str = "thumbnails/"

# Shared retry decorator for external service calls (Modal, GDrive, S3)
# Individual modules may use this directly or define their own with extra exception types.
EXTERNAL_SERVICE_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

default_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(EXTERNAL_SERVICE_RETRY_EXCEPTIONS),
    reraise=True,
)
