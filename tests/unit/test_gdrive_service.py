"""Unit tests for Google Drive service helpers."""

from unittest.mock import patch

import pytest

from nic.services.gdrive import _gdrive_query_literal, build_drive_service


@pytest.mark.unit
class TestGdriveQueryEscaping:
    def test_escapes_single_quotes(self):
        literal = _gdrive_query_literal("folder'abc")
        assert literal == "'folder\\'abc'"

    def test_escapes_backslashes(self):
        literal = _gdrive_query_literal(r"folder\abc")
        assert literal == r"'folder\\abc'"


@pytest.mark.unit
class TestBuildDriveService:
    def test_invalid_json_raises_value_error(self):
        """Invalid JSON string should raise ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Invalid service account JSON format"):
            build_drive_service("not valid json {{{")

    def test_missing_credential_fields_raises_value_error(self):
        """Valid JSON but missing required service account fields should raise ValueError."""
        # Valid JSON, but not a valid service account credential
        with pytest.raises(ValueError, match="Invalid service account credentials"):
            build_drive_service('{"type": "not_a_service_account"}')

    def test_empty_json_object_raises_value_error(self):
        """Empty JSON object should raise ValueError for missing fields."""
        with pytest.raises(ValueError, match="Invalid service account credentials"):
            build_drive_service("{}")

    def test_valid_credentials_builds_service(self):
        """Valid service account JSON should return a drive service object."""
        mock_creds = object()
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_info",
                return_value=mock_creds,
            ),
            patch("googleapiclient.discovery.build", return_value="mock-service") as mock_build,
        ):
            result = build_drive_service('{"type": "service_account", "project_id": "test"}')

        assert result == "mock-service"
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)
