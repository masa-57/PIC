# Deployment Rollback Procedures

This document covers rollback procedures for all PIC infrastructure components.

## Railway API Rollback

Railway maintains a history of deployments. To roll back:

1. Open the Railway dashboard and navigate to the PIC project.
2. Select the API service.
3. Go to the **Deployments** tab.
4. Find the last known-good deployment and click **Redeploy**.
5. Monitor the deployment logs to confirm the rollback succeeds.

Railway auto-deploys from the `main` branch. If the bad commit is already on `main`,
revert the commit in Git and push to `main` to trigger a clean deploy:

```bash
git revert <bad-commit-sha>
git push origin main
```

## Modal Workers Rollback

Modal deployments are triggered by CI/CD on push to `main`. To roll back:

1. Identify the last known-good commit SHA from the CI/CD history.
2. Re-run the `deploy-modal` job from that commit in GitHub Actions, or:

```bash
git checkout <good-commit-sha>
uv sync --frozen
uv run modal deploy src/pic/modal_app.py
```

Alternatively, revert the offending commit on `main` and let CI/CD redeploy:

```bash
git revert <bad-commit-sha>
git push origin main
```

## Database Rollback (Alembic)

To revert the most recent migration:

```bash
uv run alembic downgrade -1
```

To revert to a specific revision:

```bash
uv run alembic downgrade <revision-id>
```

After reverting, verify the current state:

```bash
uv run alembic current
uv run alembic history --verbose
```

To validate that a migration is reversible (downgrade then upgrade roundtrip):

```bash
python3 scripts/rollback_check.py
```

### Important Notes

- Always take a logical backup before running `alembic downgrade` in production.
- Some migrations may not be fully reversible (e.g., data migrations that drop columns).
  Review the downgrade function before running.
- Set `PIC_DATABASE_URL` to the target database before running Alembic commands.

## Neon Point-in-Time Recovery

Neon supports branching and point-in-time recovery (PITR):

1. Open the Neon console and select the PIC project.
2. Navigate to **Branches**.
3. Create a new branch from a point in time before the incident:
   - Select the production branch as the parent.
   - Set the restore point timestamp (UTC).
4. Verify data integrity on the new branch by running smoke tests against it.
5. Once verified, update `PIC_DATABASE_URL` to point to the restored branch.
6. Redeploy the API (Railway) and workers (Modal) with the updated URL.

### Neon Branch Cleanup

After confirming the restored branch is stable, delete the old (corrupt) branch
from the Neon console to avoid confusion and unnecessary storage usage.

## Emergency Contacts and Escalation

| Level | Action | Contact |
|-------|--------|---------|
| L1 | Service degradation detected | On-call engineer via team Slack channel |
| L2 | Rollback required, data intact | Engineering lead |
| L3 | Data loss or corruption | Engineering lead + database admin |

### Escalation Procedure

1. Detect the issue (monitoring alerts, user reports, or smoke test failures).
2. Assess severity: is the service down, degraded, or is data at risk?
3. If data is at risk, freeze write traffic immediately (disable API key or scale to zero).
4. Execute the appropriate rollback procedure above.
5. Notify stakeholders via the team Slack channel.
6. After resolution, write a postmortem documenting timeline, root cause, and follow-up actions.
