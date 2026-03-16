# Roadmap

This document outlines likely next improvements for PIC. Contributions are
welcome for any of these items.

There are currently no open roadmap issues. The items below are prospective
next investments rather than committed milestones.

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

### URL Ingest Hardening And Worker Reliability

`POST /api/v1/images/ingest` now blocks private and local-network targets,
revalidates redirect hops, and restores correct Modal dispatch and follow-up job
chaining.

### Explicit Auth Opt-Out And Metrics Alignment

Auth now requires an explicit `PIC_AUTH_DISABLED=true` opt-out, and the
documented `/metrics` behavior matches the live authenticated endpoint and
background job metrics.

### Documentation Reconciliation

README, deployment guides, Google Drive setup docs, changelog entries, and
contributor guidance were brought back in sync with the deployed system after
the `v0.2.1` release.
