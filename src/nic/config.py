import json
import logging
from pathlib import Path

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database (Neon PostgreSQL)
    database_url: str = "postgresql+asyncpg://localhost:5432/nic"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_ssl_ca: str = ""  # Path to custom CA cert for DB TLS verification

    # Object Storage (Cloudflare R2, S3-compatible)
    s3_bucket: str = "nic-images"
    s3_endpoint_url: str = ""  # R2 endpoint URL
    s3_access_key_id: str = ""  # R2 API token access key
    s3_secret_access_key: str = ""  # R2 API token secret key

    # Embedding
    dinov2_model: str = "facebook/dinov2-base"
    embedding_batch_size: int = 32
    phash_size: int = 16  # 256-bit hash

    # Level 1 Clustering (HDBSCAN on cosine distance)
    l1_min_cluster_size: int = 2  # Minimum images to form an L1 group
    l1_min_samples: int = 1  # HDBSCAN min_samples (controls density)
    l1_cluster_selection_epsilon: float = 0.10  # Max cosine distance for cluster merging
    l1_hash_threshold: int = 12  # Max Hamming distance for pHash duplicate search API

    # Level 2 Clustering
    l2_min_cluster_size: int = 5
    l2_min_samples: int = 3
    l2_umap_n_components: int = 25
    l2_umap_n_neighbors: int = 30
    hnsw_ef_search: int = 100  # HNSW ef_search for recall/speed trade-off (higher = better recall)

    # API
    api_key: str = ""  # If empty, auth is disabled (dev mode)
    cors_origins: list[str] = []  # Empty = no CORS; set explicitly in production
    cors_allow_credentials: bool = False  # Set True only with specific origins, not "*"
    max_upload_size_mb: int = 20
    max_image_download_mb: int = 50  # Max image size for pipeline download
    max_concurrent_downloads: int = 10  # Concurrent S3 downloads in pipeline discovery
    thumbnail_width: int = 256
    thumbnail_height: int = 256
    presigned_url_expiry: int = 900  # Seconds (15 minutes)
    presigned_url_max_expiry: int = 86_400  # Clamp presigned URLs to <= 24h
    rate_limit_default: str = "60/minute"
    rate_limit_burst: str = "10/second"
    job_trigger_rate_limit: str = "5/minute"
    job_queue_max_pending: int = 100
    max_pagination_offset: int = 10_000
    stale_job_timeout_minutes: int = 90  # Must exceed longest Modal function timeout (60min + buffer)

    # Observability
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    sentry_dsn: str = ""  # Empty = Sentry disabled

    # Google Drive Sync (optional — empty = disabled)
    gdrive_service_account_json: str = ""  # Service account JSON credentials as string
    gdrive_folder_id: str = ""  # Shared folder ID to sync from

    # Paths (local dev)
    data_dir: Path = Path("data")

    model_config = {"env_prefix": "NIC_", "env_file": ".env", "extra": "ignore"}

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if not hasattr(logging, v) or not isinstance(getattr(logging, v), int):
            raise ValueError(f"Invalid log level: {v}. Must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return v

    @field_validator("phash_size")
    @classmethod
    def validate_phash_size(cls, v: int) -> int:
        if v < 4 or v > 32:
            raise ValueError("phash_size must be between 4 and 32")
        return v

    @field_validator(
        "db_pool_size",
        "db_pool_max_overflow",
        "db_pool_timeout",
        "job_queue_max_pending",
        "max_pagination_offset",
        "presigned_url_max_expiry",
    )
    @classmethod
    def validate_positive_ints(cls, v: int) -> int:
        if v < 1:
            raise ValueError("value must be >= 1")
        return v

    @field_validator("cors_allow_credentials")
    @classmethod
    def validate_cors_credentials(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("cors_origins") == ["*"]:
            raise ValueError("cors_allow_credentials=True with wildcard origins is insecure")
        return v

    @model_validator(mode="after")
    def validate_s3_credentials(self) -> "Settings":
        if self.s3_endpoint_url and (not self.s3_access_key_id or not self.s3_secret_access_key):
            raise ValueError(
                "S3 credentials (NIC_S3_ACCESS_KEY_ID, NIC_S3_SECRET_ACCESS_KEY) "
                "are required when NIC_S3_ENDPOINT_URL is set"
            )
        return self

    @model_validator(mode="after")
    def validate_cors_wildcard_blocked_in_production(self) -> "Settings":
        """Block CORS wildcard in production (when api_key is set)."""
        if self.cors_origins == ["*"] and self.api_key:
            raise ValueError(
                "CORS wildcard ['*'] is not allowed when NIC_API_KEY is set (production mode). "
                "Specify explicit origins in NIC_CORS_ORIGINS."
            )
        return self

    @model_validator(mode="after")
    def validate_gdrive_json(self) -> "Settings":
        if self.gdrive_service_account_json:
            try:
                data = json.loads(self.gdrive_service_account_json)
                if not isinstance(data, dict) or "type" not in data:
                    raise ValueError("GDrive JSON must contain 'type' field")
            except json.JSONDecodeError as e:
                raise ValueError(f"NIC_GDRIVE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}") from e
        return self

    @property
    def sync_database_url(self) -> str:
        """Synchronous DB URL for Alembic migrations."""
        return self.database_url.replace("asyncpg", "psycopg2").replace("+asyncpg", "")


settings = Settings()
