# Technical Debt

Last updated: 2026-03-16

## Overview

PIC tracks technical debt through GitHub Issues. This document provides a
high-level summary of known areas for improvement.

For the full list of open issues, see:
[GitHub Issues](https://github.com/masa-57/pic/issues?q=is%3Aissue+is%3Aopen)

The items below were validated against the current codebase on 2026-03-16 and
are now tracked as open GitHub issues.

## Current Watch Areas

### Performance

- [#58](https://github.com/masa-57/pic/issues/58) Optimize Google Drive sync
  batch processing to reduce serial storage work
- [#59](https://github.com/masa-57/pic/issues/59) Paginate or stream the
  cluster visualization instead of loading the full hierarchy into memory
- [#60](https://github.com/masa-57/pic/issues/60) Reduce redundant database
  round trips in list and summary API endpoints

### Architecture

- [#61](https://github.com/masa-57/pic/issues/61) Extract database-heavy API
  route logic into service-layer functions
- [#62](https://github.com/masa-57/pic/issues/62) Introduce a worker
  dispatcher abstraction to decouple ML job submission from Modal

### Testing

- [#63](https://github.com/masa-57/pic/issues/63) Raise automated coverage on
  low-covered worker and service modules
- [#64](https://github.com/masa-57/pic/issues/64) Add higher-fidelity
  clustering integration tests that exercise real similarity behavior

### DevOps

- [#65](https://github.com/masa-57/pic/issues/65) Align the staging workflow
  quality gates with main CI/CD

## Recently Retired

Multiple reviews identified and resolved 150+ issues including:

- Transaction safety in clustering pipeline
- Memory optimization for large image sets
- Connection pool tuning
- Decompression bomb protection
- CI/CD hardening (permissions, rollback mechanism, container scanning)
- Error response consistency (RFC 7807 ProblemDetail)
- Presigned URL cache TTL
- URL-ingest worker dispatch and follow-up job chaining regressions (#54)
- SSRF protections for URL ingestion, including redirect and DNS checks (#49)
- Explicit auth opt-out and authenticated `/metrics` behavior documentation (#50, #52)
- README, deployment docs, and contributor guide drift from the live system (#53)
