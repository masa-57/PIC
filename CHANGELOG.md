# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Pluggable storage backend system with `StorageBackend` Protocol
- S3 storage backend (default, wraps existing boto3 integration)
- Google Cloud Storage backend (`PIC_STORAGE_BACKEND=gcs`)
- Local filesystem storage backend (`PIC_STORAGE_BACKEND=local`) with automatic static file serving
- URL-based image ingestion endpoint (`POST /api/v1/images/ingest`) with rate limiting
- URL ingest worker with concurrent downloads, content validation, and deduplication
- `source_url` column on images table to track original image URLs
- Alembic migration for `source_url` column
- Integration tests for URL ingest endpoint

### Fixed
- Support shared rate limit storage for multi-instance deployments (#17)
- Make Google Drive OAuth scopes configurable (#8)

### Changed
- Split `main.py` into `core/middleware.py`, `core/exception_handlers.py`, and `api/health.py`
- Refactored `image_store.py` to delegate to pluggable `StorageBackend` instead of direct boto3 calls

## [0.1.0] - 2026-02-24

### Added
- Initial open-source release of PIC (Product Image Clustering)
- Two-level hierarchical clustering: HDBSCAN on DINOv2 cosine distance (L1) + UMAP/HDBSCAN on DINOv2 embeddings (L2)
- FastAPI REST API with image, cluster, product, search, and pipeline endpoints
- Modal serverless GPU workers for embedding generation and clustering
- Google Drive sync integration for automated image ingestion
- PostgreSQL with pgvector backend for vector similarity search
- S3-compatible object storage support (tested with Cloudflare R2)
- Pipeline API for end-to-end workflows: discover, deduplicate, ingest, cluster
- API key authentication
- Alembic database migrations
- Comprehensive test suite (unit + integration)
- Docker Compose for local development
- CI/CD pipeline with GitHub Actions

[0.1.0]: https://github.com/masa-57/pic/releases/tag/v0.1.0
