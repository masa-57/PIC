# Technical Debt

Last updated: 2026-02-24

## Overview

PIC tracks technical debt through GitHub Issues. This document provides a
high-level summary of known areas for improvement.

For the full list of open issues, see:
[GitHub Issues](https://github.com/masa-57/pic/issues?q=is%3Aissue+is%3Aopen)

## Known Areas

### Performance

- Serial S3 operations in some worker paths could benefit from concurrency
- Visualization endpoint loads all images into memory (needs pagination)
- Some API list endpoints issue sequential DB queries that could be parallelized

### Architecture

- API layer contains direct `db.execute()` calls that could be extracted into a service layer

### Testing

- Several service modules have low or no direct test coverage
- Integration test embeddings use simplified vectors that don't fully exercise similarity logic

### DevOps

- Staging workflow has fewer quality gates than the production CI/CD pipeline

## Previously Resolved

Multiple reviews identified and resolved 150+ issues including:

- Transaction safety in clustering pipeline
- Memory optimization for large image sets
- Connection pool tuning
- Decompression bomb protection
- CI/CD hardening (permissions, rollback mechanism, container scanning)
- Error response consistency (RFC 7807 ProblemDetail)
- Presigned URL cache TTL
