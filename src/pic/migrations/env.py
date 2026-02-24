"""Alembic environment configuration."""

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

from nic.models.db import Base

# Load .env so NIC_DATABASE_URL is available (pydantic_settings does this
# automatically, but Alembic env.py uses os.environ directly).
load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_sync_url() -> str:
    """Get synchronous database URL for migrations."""
    url = os.environ.get("NIC_DATABASE_URL", "postgresql://localhost:5432/nic")
    # Convert async URL to sync for Alembic
    return url.replace("postgresql+asyncpg://", "postgresql://")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = create_engine(get_sync_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
