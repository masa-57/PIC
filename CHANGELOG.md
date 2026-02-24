# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-24

### Added
- Initial open-source release of PIC (Product Image Clustering)
- Two-level hierarchical clustering: pHash (L1) + DINOv2/HDBSCAN (L2)
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
