"""Unit tests for the Alembic database URL builder."""

import pytest

from pic.core.db_url import migration_url

pytestmark = pytest.mark.unit


def test_converts_asyncpg_to_psycopg2() -> None:
    assert (
        migration_url("postgresql+asyncpg://u:p@localhost:5432/pic") == "postgresql+psycopg2://u:p@localhost:5432/pic"
    )


def test_remote_host_defaults_to_verify_full() -> None:
    url = migration_url("postgresql+asyncpg://u:p@db.example.com:5432/pic")
    assert url.endswith("?sslmode=verify-full")


def test_remote_host_upgrades_weak_sslmode() -> None:
    url = migration_url("postgresql+asyncpg://u:p@db.example.com/pic?sslmode=require")
    assert url.endswith("?sslmode=verify-full")


def test_explicit_disable_is_honoured() -> None:
    url = migration_url("postgresql+asyncpg://pic:pic_local@db:5432/pic?sslmode=disable")
    assert url == "postgresql+psycopg2://pic:pic_local@db:5432/pic?sslmode=disable"


def test_ssl_ca_added_for_remote_host() -> None:
    url = migration_url("postgresql+asyncpg://u:p@db.example.com/pic", ssl_ca="/certs/ca.pem")
    assert "sslrootcert=%2Fcerts%2Fca.pem" in url
