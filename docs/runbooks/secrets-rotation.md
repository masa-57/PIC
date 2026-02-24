# Secrets Rotation Runbook

## Secret Inventory

| Secret | Location | Rotation Frequency |
|--------|----------|--------------------|
| `NIC_API_KEY` | Railway env, Modal `nic-env` | Quarterly |
| `NIC_DATABASE_URL` | Railway env, Modal `nic-env` | On compromise |
| `NIC_S3_ACCESS_KEY_ID` | Railway env, Modal `nic-env` | Quarterly |
| `NIC_S3_SECRET_ACCESS_KEY` | Railway env, Modal `nic-env` | Quarterly |
| `NIC_GDRIVE_SERVICE_ACCOUNT_JSON` | Modal `nic-env` | Annually |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | GitHub Actions secrets | Quarterly |
| `NIC_SENTRY_DSN` | Railway env | On compromise |

## Rotation Procedures

### 1. API Key Rotation

1. Generate a new key:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update Railway: `railway variables set NIC_API_KEY=<new-key>`
3. Update Modal: `modal secret set nic-env NIC_API_KEY=<new-key>`
4. Update n8n HTTP credentials with the new key
5. Verify: `curl -H "X-API-Key: <new-key>" https://<api-host>/health`

### 2. Database URL Rotation

1. Rotate the password in the Neon dashboard
2. Build the new connection string: `postgresql+asyncpg://<user>:<new-pass>@<host>/<db>?sslmode=require`
3. Update Railway: `railway variables set NIC_DATABASE_URL=<new-url>`
4. Update Modal: `modal secret set nic-env NIC_DATABASE_URL=<new-url>`
5. Verify: `curl -H "X-API-Key: <key>" https://<api-host>/health/detailed` (check `database: connected`)

### 3. S3/R2 Credential Rotation

1. Create a new API token in Cloudflare R2 dashboard
2. Update Railway:
   ```bash
   railway variables set NIC_S3_ACCESS_KEY_ID=<new-id>
   railway variables set NIC_S3_SECRET_ACCESS_KEY=<new-secret>
   ```
3. Update Modal:
   ```bash
   modal secret set nic-env NIC_S3_ACCESS_KEY_ID=<new-id> NIC_S3_SECRET_ACCESS_KEY=<new-secret>
   ```
4. Verify: trigger a test ingest and confirm S3 operations succeed
5. Revoke the old token in Cloudflare

### 4. Modal Token Rotation

1. Generate a new token in the Modal dashboard
2. Update GitHub Actions secrets: `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`
3. Verify: push a commit and confirm the CI Modal deploy step succeeds

### 5. GDrive Service Account Key Rotation

1. Generate a new key in Google Cloud Console (IAM > Service Accounts)
2. Base64-encode the JSON or store as raw string
3. Update Modal: `modal secret set nic-env NIC_GDRIVE_SERVICE_ACCOUNT_JSON='<json>'`
4. Verify: trigger a GDrive sync job and confirm files are discovered
5. Delete the old key in Google Cloud Console

## Post-Rotation Checklist

- [ ] Old credentials revoked/deleted
- [ ] API health check passes (`/health/detailed`)
- [ ] Pipeline job completes successfully
- [ ] n8n workflow runs without auth errors
- [ ] No error spikes in Sentry (if configured)
