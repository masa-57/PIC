# Secrets Rotation Runbook

## Where settings live

PIC reads its settings from `PIC_*` environment variables. Where you set them depends on how you run it:

- **Docker Compose (default)**: the `x-pic-env` block in `docker-compose.yml`, shared by the `api` and `worker` services. Compose does not load a `.env` file into the containers. After a change, recreate both containers with `docker compose up -d api worker`. If you keep secrets out of `docker-compose.yml` by adding an `env_file:` to both services, edit that file instead; the restart step is the same.
- **Native processes**: the environment or `.env` file of the `fastapi` process and of `pic-worker`. Restart both.
- **Modal backend**: the Modal secret `pic-env`, read by the Modal functions. Update it in the Modal dashboard, or recreate it with `uv run modal secret create --force pic-env ...` (this replaces the whole secret, so pass every value). New function runs pick it up.

The API and the worker read settings only at start, so always restart them after a change.

## Secret inventory

| Secret | Needed by | Rotation frequency |
|--------|-----------|--------------------|
| `PIC_API_KEY` | API only | Quarterly, or when someone with access leaves |
| `PIC_DATABASE_URL` (contains the DB password) | API, worker, Modal `pic-env` | On compromise, or per your policy |
| `PIC_S3_ACCESS_KEY_ID` / `PIC_S3_SECRET_ACCESS_KEY` | API, worker, Modal `pic-env` (S3-compatible storage) | Quarterly |
| `PIC_GCS_CREDENTIALS_JSON` | API, worker, Modal `pic-env` (GCS storage) | Annually |
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` | API, worker, Modal `pic-env` (Google Drive sync) | Annually |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | API host (Modal backend), GitHub Actions secrets (CI deploy) | Quarterly |

"Worker" means the Compose `worker` service or a native `pic-worker`. Skip Modal `pic-env` if you do not use the Modal backend, and skip rows for features you do not use.

## Rotation procedures

### 1. API key

1. Generate a new key:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Set `PIC_API_KEY` on the API (Compose: `x-pic-env`) and recreate the `api` container. The worker and Modal do not use it.
3. Update every API client and script that sends the `X-API-Key` header.
4. Verify: `curl -H "X-API-Key: <new-key>" https://<api-host>/health/detailed` returns 200, and the old key returns 401.

Rotating the key logs everyone out of the web UI. The `pic_session` cookie is derived from the key, so all existing sessions stop working and users log in again at `/ui/login` with the new key.

### 2. Database password

1. Change the database role's password. With your own Postgres, `ALTER ROLE <user> PASSWORD '<new-pass>';`. With a hosted provider (for example Neon, AWS RDS, Supabase), use its dashboard.
2. Build the new URL: `postgresql+asyncpg://<user>:<new-pass>@<host>:5432/<db>?sslmode=verify-full` (for a remote host).
3. Update `PIC_DATABASE_URL` on the API and the worker, and in Modal `pic-env` if used.
4. Restart the API and the worker.
5. Verify: `curl -H "X-API-Key: <key>" https://<api-host>/health/detailed` shows `"database": "connected"`, and the worker logs show no connection errors.

For the Compose `db` service: its password is `POSTGRES_PASSWORD` in `docker-compose.yml`, which only takes effect when the data volume is first created. To change it on an existing volume, run `ALTER ROLE` inside the container (`docker compose exec db psql -U pic -d pic`), then update `PIC_DATABASE_URL` in `x-pic-env` and `POSTGRES_PASSWORD` to match. The Compose database listens on `127.0.0.1` only.

### 3. S3-compatible storage keys

Works the same for AWS S3, Cloudflare R2, MinIO and other S3-compatible services.

1. Create a new access key in your provider's console (for example, an R2 API token in the Cloudflare dashboard, or an IAM access key in AWS). Give it read and write access to the PIC bucket.
2. Update `PIC_S3_ACCESS_KEY_ID` and `PIC_S3_SECRET_ACCESS_KEY` on the API and the worker, and in Modal `pic-env` if used.
3. Restart the API and the worker.
4. Verify: run a pipeline (web UI **Runs**, or `POST /api/v1/pipeline/run`) and check that it completes, and that thumbnails load in the web UI.
5. Revoke the old key in the provider's console.

### 4. GCS service account key

1. Create a new JSON key for the storage service account in Google Cloud Console (IAM & Admin > Service Accounts > Keys).
2. Update `PIC_GCS_CREDENTIALS_JSON` (the JSON as a single-line string) on the API and the worker, and in Modal `pic-env` if used.
3. Restart the API and the worker, then verify as for S3.
4. Delete the old key.

### 5. Modal token

1. Create a new token in the Modal dashboard.
2. Update `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` in the GitHub Actions secrets (for the CI deploy) and on the API host if it uses the Modal backend. Restart the API.
3. Verify: create a job (for example, run clustering) and check that it starts; push to `main` and check the `deploy-modal` job succeeds.
4. Revoke the old token in the Modal dashboard.

### 6. Google Drive service account key

1. Create a new JSON key for the service account in Google Cloud Console (IAM & Admin > Service Accounts > Keys).
2. Update `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` (the JSON as a single-line string) on the API and the worker, and in Modal `pic-env` if used.
3. Restart the API and the worker.
4. Verify: start a sync (web UI **Runs** > **Google Drive** > **Sync now**, or `POST /api/v1/gdrive/sync`) and check that the job completes.
5. Delete the old key in Google Cloud Console.

## Post-rotation checklist

- [ ] Old credentials revoked or deleted
- [ ] `/health/detailed` returns `"status": "ok"`
- [ ] A pipeline run completes
- [ ] API clients and scripts work with the new values (no 401s)
- [ ] You can log in to the web UI
- [ ] No new errors in the API and worker logs (`docker compose logs -f api worker`)
