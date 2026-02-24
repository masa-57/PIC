"""Test that Alembic migrations can upgrade and downgrade cleanly.

Requires a running PostgreSQL instance with pgvector. The integration-test
CI job already provides this via a service container.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def _make_alembic_config() -> Config:
    """Build Alembic config pointing at the test database."""
    cfg = Config("alembic.ini")
    db_url = os.environ.get("NIC_DATABASE_URL", "postgresql+asyncpg://localhost:5432/nic")
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


def _sync_url() -> str:
    db_url = os.environ.get("NIC_DATABASE_URL", "postgresql+asyncpg://localhost:5432/nic")
    return db_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.mark.integration
def test_migrations_upgrade_to_head():
    """All migrations apply cleanly from an empty database to head."""
    cfg = _make_alembic_config()

    # Drop all tables first to start from clean state
    engine = create_engine(_sync_url(), poolclass=NullPool)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    engine.dispose()

    command.upgrade(cfg, "head")


@pytest.mark.integration
def test_migrations_downgrade_one_step_and_reupgrade():
    """Downgrade one revision from head and re-upgrade cleanly."""
    cfg = _make_alembic_config()

    # Start from clean state
    engine = create_engine(_sync_url(), poolclass=NullPool)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    engine.dispose()

    # Upgrade to head
    command.upgrade(cfg, "head")

    # Downgrade one step
    command.downgrade(cfg, "-1")

    # Re-upgrade back to head
    command.upgrade(cfg, "head")
