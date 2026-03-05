import json
import logging
from pathlib import Path

from pydantic import ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime environment
    env: str = "development"  # development, staging, production, test

    # Database (Neon PostgreSQL)
    database_url: str = "postgresql+asyncpg://localhost:5432/pic"
    postgres_url: str = ""  # Optional sync URL for CLI tools (backup/restore)
    db_pool_size: int = 10
    db_pool_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_ssl_ca: str = ""  # Path to custom CA cert for DB TLS verification

    # Storage backend selection
    storage_backend: str = "s3"  # "s3" | "gcs" | "local"

    # Object Storage (Cloudflare R2, S3-compatible)
    s3_bucket: str = "pic-images"
    s3_endpoint_url: str = ""  # R2 endpoint URL
    s3_access_key_id: str = ""  # R2 API token access key
    s3_secret_access_key: str = ""  # R2 API token secret key

    # Google Cloud Storage (required when storage_backend=gcs)
    gcs_bucket: str = ""
    gcs_project_id: str = ""
    gcs_credentials_json: str = ""  # Service account JSON

    # Local filesystem storage (required when storage_backend=local)
    local_storage_path: Path = Path("data/storage")
    local_storage_base_url: str = ""  # e.g., http://localhost:8000/files

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
    auth_disabled: bool = False  # Explicit acknowledgment for unauthenticated development mode
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
    rate_limit_storage_url: str = ""  # Redis URI for shared rate limiting (e.g., redis://localhost:6379)
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
    # Use drive.readonly if move-to-processed not needed
    gdrive_scopes: list[str] = ["https://www.googleapis.com/auth/drive"]

    # Paths (local dev)
    data_dir: Path = Path("data")

    model_config = {"env_prefix": "PIC_", "env_file": ".env", "extra": "ignore"}

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

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        env = v.lower().strip()
        if env not in {"development", "staging", "production", "test"}:
            raise ValueError("env must be one of: development, staging, production, test")
        return env

    @field_validator("storage_backend")
    @classmethod
    def validate_storage_backend(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"s3", "gcs", "local"}:
            raise ValueError("storage_backend must be one of: s3, gcs, local")
        return v

    @field_validator(
        "db_pool_size",
        "db_pool_max_overflow",
        "db_pool_timeout",
        "job_queue_max_pending",
        "max_pagination_offset",
        "presigned_url_max_expiry",
        "hnsw_ef_search",
    )
    @classmethod
    def validate_positive_ints(cls, v: int) -> int:
        if v < 1:
            raise ValueError("value must be >= 1")
        return v

    @field_validator("hnsw_ef_search")
    @classmethod
    def validate_hnsw_ef_search(cls, v: int) -> int:
        if v > 1000:
            raise ValueError("hnsw_ef_search must be <= 1000")
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
                "S3 credentials (PIC_S3_ACCESS_KEY_ID, PIC_S3_SECRET_ACCESS_KEY) "
                "are required when PIC_S3_ENDPOINT_URL is set"
            )
        return self

    @model_validator(mode="after")
    def validate_cors_wildcard_blocked_in_production(self) -> "Settings":
        """Block CORS wildcard in production (when api_key is set)."""
        if self.cors_origins == ["*"] and self.api_key:
            raise ValueError(
                "CORS wildcard ['*'] is not allowed when PIC_API_KEY is set (production mode). "
                "Specify explicit origins in PIC_CORS_ORIGINS."
            )
        return self

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        """Prevent accidental unauthenticated production deployments."""
        if self.env == "production" and not self.api_key and not self.auth_disabled:
            raise ValueError(
                "PIC_API_KEY is required when PIC_ENV=production. "
                "Set PIC_AUTH_DISABLED=true only if you explicitly intend unauthenticated mode."
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
                raise ValueError(f"PIC_GDRIVE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}") from e
        return self

    @model_validator(mode="after")
    def validate_gcs_credentials(self) -> "Settings":
        if self.storage_backend == "gcs":
            if not self.gcs_bucket:
                raise ValueError("PIC_GCS_BUCKET is required when PIC_STORAGE_BACKEND=gcs")
            if not self.gcs_credentials_json:
                raise ValueError("PIC_GCS_CREDENTIALS_JSON is required when PIC_STORAGE_BACKEND=gcs")
        return self

    @model_validator(mode="after")
    def validate_local_storage_not_in_production(self) -> "Settings":
        if self.storage_backend == "local" and self.env == "production":
            raise ValueError("Local storage backend is not allowed in production")
        return self

    @property
    def sync_database_url(self) -> str:
        """Synchronous DB URL for Alembic migrations."""
        return self.database_url.replace("asyncpg", "psycopg2").replace("+asyncpg", "")


try:
    settings = Settings()
except ValidationError as exc:
    raise RuntimeError(
        "Invalid PIC configuration. Review PIC_* environment variables in your shell/.env and retry startup."
    ) from exc
