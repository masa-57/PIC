"""Unit tests for HNSW migration DDL safety."""

import importlib
from unittest.mock import patch

import pytest


class _AutocommitBlock:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def __enter__(self) -> None:
        self._events.append("enter")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._events.append("exit")
        return False


class _FakeMigrationContext:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def autocommit_block(self) -> _AutocommitBlock:
        self._events.append("autocommit_block")
        return _AutocommitBlock(self._events)


def _run_migration(module_name: str, fn_name: str) -> tuple[list[str], list[str]]:
    module = importlib.import_module(module_name)
    events: list[str] = []
    sql_calls: list[str] = []
    fake_context = _FakeMigrationContext(events)

    with (
        patch.object(module.op, "get_context", return_value=fake_context),
        patch.object(module.op, "execute", side_effect=lambda sql: sql_calls.append(str(sql))),
    ):
        getattr(module, fn_name)()

    return events, sql_calls


@pytest.mark.unit
def test_migration_003_upgrade_uses_concurrent_index_creation() -> None:
    events, sql_calls = _run_migration("pic.migrations.versions.003_add_hnsw_vector_index", "upgrade")
    assert events == ["autocommit_block", "enter", "exit"]
    assert len(sql_calls) == 1
    sql = sql_calls[0].lower()
    assert "create index concurrently if not exists ix_images_embedding_hnsw" in sql


@pytest.mark.unit
def test_migration_003_downgrade_uses_concurrent_index_drop() -> None:
    events, sql_calls = _run_migration("pic.migrations.versions.003_add_hnsw_vector_index", "downgrade")
    assert events == ["autocommit_block", "enter", "exit"]
    assert len(sql_calls) == 1
    sql = sql_calls[0].lower()
    assert "drop index concurrently if exists ix_images_embedding_hnsw" in sql


@pytest.mark.unit
def test_migration_015_upgrade_uses_concurrent_drop_and_create() -> None:
    events, sql_calls = _run_migration("pic.migrations.versions.015_tune_hnsw_index_params", "upgrade")
    assert events == ["autocommit_block", "enter", "exit"]
    assert len(sql_calls) == 2
    assert "drop index concurrently if exists ix_images_embedding_hnsw" in sql_calls[0].lower()
    assert "create index concurrently ix_images_embedding_hnsw" in sql_calls[1].lower()


@pytest.mark.unit
def test_migration_015_downgrade_uses_concurrent_drop_and_create() -> None:
    events, sql_calls = _run_migration("pic.migrations.versions.015_tune_hnsw_index_params", "downgrade")
    assert events == ["autocommit_block", "enter", "exit"]
    assert len(sql_calls) == 2
    assert "drop index concurrently if exists ix_images_embedding_hnsw" in sql_calls[0].lower()
    assert "create index concurrently ix_images_embedding_hnsw" in sql_calls[1].lower()
