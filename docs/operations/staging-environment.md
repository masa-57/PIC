# Staging Environment

This document describes how to set up and maintain a staging environment
for the PIC project.

## Overview

The staging environment mirrors production to catch issues before they
reach users. It consists of:

- A separate Railway project (or environment) for the API.
- A Neon database branch for isolated staging data.
- A separate Modal deployment using staging secrets.
- A dedicated R2 bucket (or prefix) for staging images.

## Railway Staging Project

### Option A: Separate Railway Project

1. Create a new Railway project named `pic-staging` in the Railway dashboard.
2. Link the same GitHub repository (`masa-57/pic`).
3. Configure auto-deploy from the `staging` branch instead of `main`.
4. Set all staging environment variables (see Configuration below).

### Option B: Railway Environments

Railway supports multiple environments within a single project:

1. Open the PIC project in Railway.
2. Create a new environment named `staging`.
3. Configure the `staging` environment to deploy from the `staging` branch.
4. Set environment-specific variables for staging.

## Neon Staging Database

Use Neon branching to create an isolated staging database:

1. Open the Neon console and navigate to the PIC project.
2. Create a new branch named `staging` from the production branch.
   - This gives staging a copy of the production schema without production data,
     or with a snapshot of production data for realistic testing.
3. Note the connection string for the staging branch.
4. Set `PIC_DATABASE_URL` in the staging Railway environment to the staging branch URL.

### Keeping Staging Schema in Sync

When new migrations are merged to `main`, they should also be applied to staging:

1. The `deploy-staging.yml` workflow runs migrations automatically via Modal deploy.
2. If schema drift occurs, manually run: `uv run alembic upgrade head` against the
   staging database.

### Resetting Staging Data

To reset staging data to a clean state:

1. Delete the staging branch in Neon.
2. Create a new branch from production (or from a seed state).
3. Update `PIC_DATABASE_URL` if the connection string changed.

## Staging-Specific Configuration

Set these environment variables in the staging Railway environment:

```
# Database (Neon staging branch)
PIC_DATABASE_URL=postgresql+asyncpg://<staging-neon-url>/pic_staging?sslmode=require

# API
PIC_API_KEY=<staging-api-key>
PIC_LOG_LEVEL=DEBUG
PIC_CORS_ORIGINS=["http://localhost:3000"]

# Object Storage (separate bucket or prefix)
PIC_S3_BUCKET=pic-images-staging
PIC_S3_ENDPOINT_URL=<r2-endpoint>
PIC_S3_ACCESS_KEY_ID=<staging-r2-key>
PIC_S3_SECRET_ACCESS_KEY=<staging-r2-secret>

# Modal (staging tokens)
MODAL_TOKEN_ID=<staging-modal-token-id>
MODAL_TOKEN_SECRET=<staging-modal-token-secret>

# Sentry (optional, separate project)
PIC_SENTRY_DSN=<staging-sentry-dsn>
```

## CI Workflow for Staging Deploys

The `deploy-staging.yml` workflow triggers on pushes to the `staging` branch.
It runs lint, unit tests, and deploys Modal workers using staging secrets.

See `.github/workflows/deploy-staging.yml` for the full configuration.

### Workflow Summary

1. **Lint**: ruff check, ruff format, mypy.
2. **Unit test**: pytest with coverage.
3. **Deploy Modal**: Deploy workers using staging Modal tokens.
4. Railway auto-deploys the staging project from the `staging` branch.

### Promoting to Production

To promote a staging-verified change to production:

1. Verify the change works correctly in staging.
2. Merge the `staging` branch into `main` (or cherry-pick specific commits).
3. Push to `main` to trigger the production CI/CD pipeline.
