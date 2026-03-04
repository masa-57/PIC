# Google Drive Sync — Quick Start

Drop images into a Google Drive folder and they'll be automatically clustered every 15 minutes.

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

Set the following in your deployment environment:

| Variable | Value |
|---|---|
| `PIC_GDRIVE_CREDENTIALS_JSON` | Contents of the JSON key file from step 1.4 |
| `PIC_GDRIVE_FOLDER_ID` | Folder ID copied from the URL in step 2.3 |

> **Security:** The JSON key file contains sensitive credentials. Never commit it to version control or share it over unencrypted channels.

---

## How It Works

- The system checks your folder every **15 minutes** for new images (subfolders included)
- After processing, files are moved to a `processed/` subfolder (created automatically)
- Duplicates and non-image files are skipped
- The service account can **only** access folders you explicitly share with it
- OAuth scopes default to `drive` (full access) to support the move-to-processed feature. If you don't need file moving, set `PIC_GDRIVE_SCOPES=["https://www.googleapis.com/auth/drive.readonly"]` for narrower access

---

*Questions? [Open an issue](https://github.com/masa-57/pic/issues) on GitHub.*
