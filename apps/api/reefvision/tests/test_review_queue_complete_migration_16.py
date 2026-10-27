"""Additive QC completion audit migration regressions (0039 -> 0040)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from reefvision.tests.test_review_queue_triage_migration_16 import (
    _assert_indexes,
    _insert,
    _legacy_schema,
    _migration,
)

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0040_review_queue_complete_event.py"
)


def _completion_migration():
    spec = importlib.util.spec_from_file_location("reefvision_completion_0040", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_completion_upgrade_preserves_history_and_downgrade_refuses_loss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'completion.sqlite'}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        with connection.begin():
            _legacy_schema(connection)
            old = _migration()
            monkeypatch.setattr(old, "op", Operations(MigrationContext.configure(connection)))
            old.upgrade()
            _insert(connection, "existing-triage", "triage_skip")
            migration = _completion_migration()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            _assert_indexes(connection)
            _insert(connection, "completed", "triage_complete")
            assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_item_events")) == 3
            with pytest.raises(IntegrityError):
                _insert(connection, "unsupported", "triage_approve")
            with pytest.raises(RuntimeError, match="Cannot downgrade QC completion audit"):
                migration.downgrade()
            assert (
                connection.scalar(
                    text("SELECT event_type FROM review_queue_item_events WHERE id='completed'")
                )
                == "triage_complete"
            )
            assert connection.scalar(text("PRAGMA foreign_key_check")) is None
            connection.execute(text("DELETE FROM review_queue_item_events WHERE id='completed'"))
            migration.downgrade()
            _assert_indexes(connection)
            assert (
                connection.scalar(
                    text(
                        "SELECT event_type FROM review_queue_item_events WHERE id='existing-triage'"
                    )
                )
                == "triage_skip"
            )
            with pytest.raises(IntegrityError):
                _insert(connection, "no-longer-allowed", "triage_complete")
    engine.dispose()


def test_completion_upgrade_rejects_cross_scoped_history_without_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_schema(connection)
        old = _migration()
        monkeypatch.setattr(old, "op", Operations(MigrationContext.configure(connection)))
        old.upgrade()
        connection.execute(
            text(
                "UPDATE review_queue_item_events SET review_queue_id='other_queue' "
                "WHERE id='original'"
            )
        )
        migration = _completion_migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="orphan or cross-scoped"):
            migration.upgrade()
        assert (
            connection.scalar(
                text("SELECT review_queue_id FROM review_queue_item_events WHERE id='original'")
            )
            == "other_queue"
        )
        with pytest.raises(IntegrityError):
            _insert(connection, "premature", "triage_complete")
    engine.dispose()
