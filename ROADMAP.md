# Roadmap

This document outlines planned improvements for PIC. Contributions are welcome for any of these items.

## High Priority

### Worker Abstraction Layer (Modal Decoupling)

Currently, GPU workloads (embedding generation, clustering) run exclusively on [Modal](https://modal.com). The goal is to create a `WorkerDispatcher` protocol that allows GPU workloads to run on other platforms:

- Celery + Redis
- AWS Batch
- Kubernetes Jobs
- Ray
- Local process (for development)

**Research needed:** Evaluate Celery vs Dramatiq vs a custom protocol for the simplest migration path. This is the highest-impact item for platform flexibility.

## Medium Priority

### Multi-Model Embedding Support

Support alternative vision models alongside DINOv2:

- CLIP (OpenAI)
- SigLIP (Google)
- Custom models via a plugin interface

## Future

### Webhook Notifications

Send notifications when clustering jobs complete, new clusters are detected, or pipeline stages finish.

### Batch API

Accept large batches of images in a single API call with async processing and status tracking.

### Real-Time Clustering

Stream clustering updates as new images are ingested rather than requiring explicit cluster trigger.

## Completed

### Configurable Storage Backends

Support for S3 (existing), Google Cloud Storage, and local filesystem via `PIC_STORAGE_BACKEND` env var. See [design doc](docs/plans/2026-03-04-storage-backends-and-url-ingestion-design.md).

### URL-Based Image Ingestion

`POST /api/v1/images/ingest` endpoint accepts image URLs for batch download and ingestion. See [design doc](docs/plans/2026-03-04-storage-backends-and-url-ingestion-design.md).
