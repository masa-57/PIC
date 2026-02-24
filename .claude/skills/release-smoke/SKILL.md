---
name: release-smoke
description: Run post-deploy smoke verification for Railway API and Modal workers.
---

# Release Smoke

## Inputs

- API base URL
- API key (if auth enabled)

## Procedure

1. Check API readiness:
   - `GET /health`
   - `GET /health/detailed` (authorized context)
2. Check core API behavior:
   - list endpoint (`/api/v1/images?limit=1`)
   - one write-safe trigger endpoint if allowed (e.g. dry-run job trigger)
3. Check Modal deployment:
   - `modal app list`
   - `modal function list` for app `nic`
4. Confirm no critical errors in recent logs.
5. Report pass/fail with concrete remediation if failed.

## Output

- smoke status: pass/fail
- failing checks with endpoint/command and error summary
- rollback recommendation when needed
