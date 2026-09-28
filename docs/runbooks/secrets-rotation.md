# Secrets Rotation Runbook

## Secret Inventory

| Secret | Location | Rotation Frequency |
|--------|----------|--------------------|
| `PIC_API_KEY` | API host env, Modal `pic-env` | Quarterly |
| `PIC_DATABASE_URL` | API host env, Modal `pic-env` | On compromise |
| `PIC_S3_ACCESS_KEY_ID` | API host env, Modal `pic-env` | Quarterly |
| `PIC_S3_SECRET_ACCESS_KEY` | API host env, Modal `pic-env` | Quarterly |
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` | Modal `pic-env` | Annually |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | GitHub Actions secrets | Quarterly |

## Rotation Procedures

### 1. API Key Rotation

1. Generate a new key:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `PIC_API_KEY` in the API host's environment (`.env` for docker compose) and restart the API
3. Update Modal: `modal secret set pic-env PIC_API_KEY=<new-key>`
4. Update n8n HTTP credentials with the new key
5. Verify: `curl -H "X-API-Key: <new-key>" https://<api-host>/health`

### 2. Database URL Rotation

1. Rotate the password in the Neon dashboard
2. Build the new connection string: `postgresql+asyncpg://<user>:<new-pass>@<host>/<db>?sslmode=require`
3. Update `PIC_DATABASE_URL` in the API host's environment and restart the API
4. Update Modal: `modal secret set pic-env PIC_DATABASE_URL=<new-url>`
5. Verify: `curl -H "X-API-Key: <key>" https://<api-host>/health/detailed` (check `database: connected`)

### 3. S3/R2 Credential Rotation

1. Create a new API token in Cloudflare R2 dashboard
2. Update `PIC_S3_ACCESS_KEY_ID` and `PIC_S3_SECRET_ACCESS_KEY` in the API host's environment and restart the API
3. Update Modal:
   ```bash
   modal secret set pic-env PIC_S3_ACCESS_KEY_ID=<new-id> PIC_S3_SECRET_ACCESS_KEY=<new-secret>
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
3. Update Modal: `modal secret set pic-env PIC_GDRIVE_SERVICE_ACCOUNT_JSON='<json>'`
4. Verify: trigger a GDrive sync job and confirm files are discovered
5. Delete the old key in Google Cloud Console

## Post-Rotation Checklist

- [ ] Old credentials revoked/deleted
- [ ] API health check passes (`/health/detailed`)
- [ ] Pipeline job completes successfully
- [ ] n8n workflow runs without auth errors
- [ ] No new errors in the API and worker logs
