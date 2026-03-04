"""Google Drive API wrapper for GDrive → R2 sync."""

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any

from pic.core.constants import IMAGE_EXTENSIONS, default_retry

logger = logging.getLogger(__name__)

_gdrive_retry = default_retry


@dataclass
class GDriveFile:
    """Metadata for a file discovered in Google Drive."""

    id: str
    name: str
    mime_type: str
    size: int
    parent_id: str


def build_drive_service(service_account_json: str, scopes: list[str] | None = None) -> Any:  # noqa: ANN401
    """Initialize Google Drive API client from service account JSON string.

    Args:
        service_account_json: JSON string with service account credentials.
        scopes: OAuth scopes to request.  Defaults to ``settings.gdrive_scopes``
            (``["https://www.googleapis.com/auth/drive"]``).  The full ``drive``
            scope is required when move-to-processed is enabled (create folder +
            move file).  Use ``["https://www.googleapis.com/auth/drive.readonly"]``
            if you only need read access.
    """
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    if scopes is None:
        from pic.config import settings

        scopes = settings.gdrive_scopes

    try:
        creds_info = json.loads(service_account_json)
    except json.JSONDecodeError:
        logger.exception("Failed to parse Google Drive service account JSON (invalid format)")
        raise ValueError("Invalid service account JSON format") from None

    try:
        credentials = Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            creds_info,
            scopes=scopes,
        )
    except (KeyError, ValueError):
        logger.exception("Service account JSON missing required fields")
        raise ValueError("Invalid service account credentials") from None

    return build("drive", "v3", credentials=credentials)


@_gdrive_retry
def list_image_files(service: Any, folder_id: str) -> list[GDriveFile]:  # noqa: ANN401
    """Recursively list image files in a Google Drive folder, excluding 'processed' subfolders."""
    files: list[GDriveFile] = []
    _list_files_recursive(service, folder_id, files)
    return files


def _list_files_recursive(
    service: Any,  # noqa: ANN401
    folder_id: str,
    result: list[GDriveFile],
) -> None:
    """Recursively traverse folders, collecting image files."""
    page_token: str | None = None

    while True:
        query = f"{_gdrive_query_literal(folder_id)} in parents and trashed = false"
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, size, parents)",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )

        for item in response.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                # Skip 'processed' subfolder
                if item["name"].lower() == "processed":
                    continue
                # Recurse into subfolders
                _list_files_recursive(service, item["id"], result)
            else:
                # Check if it's an image by extension
                name_lower = item["name"].lower()
                if any(name_lower.endswith(ext) for ext in IMAGE_EXTENSIONS):
                    result.append(
                        GDriveFile(
                            id=item["id"],
                            name=item["name"],
                            mime_type=item["mimeType"],
                            size=int(item.get("size", 0)),
                            parent_id=folder_id,
                        )
                    )

        page_token = response.get("nextPageToken")
        if not page_token:
            break


@_gdrive_retry
def download_file(service: Any, file_id: str) -> bytes:  # noqa: ANN401
    """Download file content from Google Drive."""
    request = service.files().get_media(fileId=file_id)
    return bytes(request.execute())


_processed_folder_cache: dict[str, str] = {}
_processed_folder_lock = threading.Lock()


@_gdrive_retry
def get_or_create_processed_folder(service: Any, parent_folder_id: str) -> str:  # noqa: ANN401
    """Find or create a 'processed' subfolder in the given parent folder. Result is cached."""
    with _processed_folder_lock:
        if parent_folder_id in _processed_folder_cache:
            return _processed_folder_cache[parent_folder_id]

    # Search for existing 'processed' folder
    query = (
        f"{_gdrive_query_literal(parent_folder_id)} in parents "
        "and name = 'processed' "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    response = service.files().list(q=query, fields="files(id)").execute()
    existing = response.get("files", [])

    if existing:
        folder_id: str = existing[0]["id"]
    else:
        # Create new 'processed' folder
        metadata = {
            "name": "processed",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        folder_id = folder["id"]
        logger.info("Created 'processed' folder %s in parent %s", folder_id, parent_folder_id)

    with _processed_folder_lock:
        _processed_folder_cache[parent_folder_id] = folder_id
    return folder_id


@_gdrive_retry
def move_file_to_folder(
    service: Any,  # noqa: ANN401
    file_id: str,
    current_parent_id: str,
    target_folder_id: str,
) -> None:
    """Move a file from one folder to another by updating parents."""
    service.files().update(
        fileId=file_id,
        addParents=target_folder_id,
        removeParents=current_parent_id,
        fields="id",
    ).execute()


def _gdrive_query_literal(value: str) -> str:
    """Escape a string as a Google Drive query single-quoted literal."""
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"
