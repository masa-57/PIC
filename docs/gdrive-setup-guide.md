# Google Drive Sync — Quick Start

Drop images into a Google Drive folder and PIC imports and clusters them. With the local worker (the default), you start each sync from the web UI or the API. With the Modal backend, PIC also checks the folder automatically every 15 minutes.

**Supported formats**: JPG, JPEG, PNG, GIF, BMP, WebP, TIFF (max 50 MB each)

---

## Setup (One-Time)

### 1. Create a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project (or use an existing one)
2. Enable the **Google Drive API** (APIs & Services > Library > search "Google Drive API" > Enable)
3. Create a service account (APIs & Services > Credentials > Create Credentials > Service Account — name it anything, skip the optional steps)
4. Create a JSON key for it (click the service account > Keys tab > Add Key > JSON) — a file downloads automatically

### 2. Share Your Drive Folder

1. In Google Drive, create a folder for your images (e.g., `Images for Clustering`)
2. Right-click the folder > **Share** > paste the service account's `client_email` (from the JSON file, looks like `name@project.iam.gserviceaccount.com`) > set to **Editor** > uncheck "Notify people" > Share
3. Copy the **Folder ID** from the URL:
   ```
   https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs
                                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                            This is the Folder ID
   ```

### 3. Configure Environment Variables

| Variable | Value |
|---|---|
| `PIC_GDRIVE_SERVICE_ACCOUNT_JSON` | Contents of the JSON key file from step 1.4, as a single-line string |
| `PIC_GDRIVE_FOLDER_ID` | Folder ID copied from the URL in step 2.3 |

Both the API and the worker need them. The API uses them to accept a sync request; the worker uses them to download the files.

- **Docker Compose (default)**: Compose does not read a `.env` file into the containers. Add both variables to the `x-pic-env` block in `docker-compose.yml` (it is shared by `api` and `worker`), then recreate the containers with `docker compose up -d`.
- **Native `pic-worker` / `fastapi`**: set them in the environment or `.env` of both processes and restart them.
- **Modal backend**: add them to the Modal secret `pic-env` as well as the API host (see [deployment/modal-setup.md](deployment/modal-setup.md)).

> **Security:** The JSON key file contains sensitive credentials. Never commit it to version control or share it over unencrypted channels.

### 4. Run a Sync

- **Web UI**: open **Runs**, pick the **Google Drive** tab, and click **Sync now**.
- **API**: `curl -X POST -H "X-API-Key: $PIC_API_KEY" http://localhost:8000/api/v1/gdrive/sync`. It returns a job; follow it with `GET /api/v1/jobs/{id}`. The endpoint returns 400 if either variable is missing on the API.
- **Modal backend only**: the `check_gdrive_for_new_files` cron checks the folder every 15 minutes and starts a sync when it finds new images. There is no automatic check with the local worker; to get one, call the API endpoint from cron or another scheduler.

---

## How It Works

- Each sync lists images in your folder, subfolders included
- After processing, files are moved to a `processed/` subfolder (created automatically) and skipped on the next sync
- Duplicates and non-image files are skipped
- If at least one new image was imported, the sync then re-clusters all images
- A sync cannot run at the same time as a pipeline run or another sync; whichever starts second fails and can be retried
- The service account can **only** access folders you explicitly share with it
- OAuth scopes default to `drive` (full access) to support the move-to-processed feature. If you don't need file moving, set `PIC_GDRIVE_SCOPES=["https://www.googleapis.com/auth/drive.readonly"]` for narrower access

---

*Questions? [Open an issue](https://github.com/masa-57/pic/issues) on GitHub.*
