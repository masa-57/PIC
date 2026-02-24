"""Unit tests for config validation (TC-2)."""

import pytest


@pytest.mark.unit
class TestPhashSizeValidator:
    def test_valid_phash_size(self):
        from nic.config import Settings

        s = Settings(phash_size=16)
        assert s.phash_size == 16

    def test_phash_size_minimum(self):
        from nic.config import Settings

        s = Settings(phash_size=4)
        assert s.phash_size == 4

    def test_phash_size_maximum(self):
        from nic.config import Settings

        s = Settings(phash_size=32)
        assert s.phash_size == 32

    def test_phash_size_too_small(self):
        from nic.config import Settings

        with pytest.raises(ValueError, match="phash_size must be between 4 and 32"):
            Settings(phash_size=2)

    def test_phash_size_too_large(self):
        from nic.config import Settings

        with pytest.raises(ValueError, match="phash_size must be between 4 and 32"):
            Settings(phash_size=64)


@pytest.mark.unit
class TestCorsCredentialsValidator:
    def test_credentials_with_wildcard_raises(self):
        from nic.config import Settings

        with pytest.raises(ValueError, match="wildcard origins is insecure"):
            Settings(cors_origins=["*"], cors_allow_credentials=True)

    def test_credentials_with_specific_origins_ok(self):
        from nic.config import Settings

        s = Settings(cors_origins=["https://example.com"], cors_allow_credentials=True)
        assert s.cors_allow_credentials is True

    def test_no_credentials_with_wildcard_ok(self):
        from nic.config import Settings

        s = Settings(cors_origins=["*"], cors_allow_credentials=False, api_key="")
        assert s.cors_allow_credentials is False


@pytest.mark.unit
class TestDefaultValues:
    def test_defaults(self):
        from nic.config import Settings

        s = Settings()
        assert s.rate_limit_default == "60/minute"
        assert s.rate_limit_burst == "10/second"
        assert s.db_pool_size == 10
        assert s.db_pool_max_overflow == 20
        assert s.db_pool_timeout == 30
        assert s.max_image_download_mb == 50
        assert s.presigned_url_expiry == 900
        assert s.l1_hash_threshold == 12
        assert s.l2_min_cluster_size == 5
        assert s.l2_min_samples == 3
        assert s.embedding_batch_size == 32


@pytest.mark.unit
class TestSyncDatabaseUrl:
    def test_asyncpg_to_psycopg2(self):
        from nic.config import Settings

        s = Settings(database_url="postgresql+asyncpg://localhost:5432/nic")
        assert "psycopg2" in s.sync_database_url
        assert "asyncpg" not in s.sync_database_url


@pytest.mark.unit
class TestExtraIgnore:
    def test_extra_env_vars_tolerated(self, monkeypatch):
        """Settings should tolerate extra NIC_* env vars without crashing."""
        monkeypatch.setenv("NIC_SOME_RANDOM_THING", "hello")
        from nic.config import Settings

        # Should not raise
        s = Settings()
        assert s is not None


@pytest.mark.unit
class TestGDriveJsonValidator:
    def test_empty_json_is_ok(self):
        """Empty gdrive_service_account_json should be accepted (disabled)."""
        from nic.config import Settings

        s = Settings(gdrive_service_account_json="")
        assert s.gdrive_service_account_json == ""

    def test_valid_json_is_accepted(self):
        """Valid service account JSON should be accepted."""
        import json

        from nic.config import Settings

        valid = json.dumps({"type": "service_account", "project_id": "test"})
        s = Settings(gdrive_service_account_json=valid)
        assert s.gdrive_service_account_json == valid

    def test_invalid_json_raises(self):
        """Malformed JSON should raise ValueError."""
        from nic.config import Settings

        with pytest.raises(ValueError, match="not valid JSON"):
            Settings(gdrive_service_account_json="not-json-{{{")

    def test_json_without_type_field_raises(self):
        """JSON without 'type' field should raise ValueError."""
        import json

        from nic.config import Settings

        with pytest.raises(ValueError, match="must contain 'type' field"):
            Settings(gdrive_service_account_json=json.dumps({"project_id": "test"}))
