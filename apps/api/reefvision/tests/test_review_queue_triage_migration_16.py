"""SQLite migration regression for the 1.6 QC audit-event type contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0039_review_queue_triage_event_types.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("reefvision_review_triage_0039", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_schema(connection) -> None:
    connection.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(text("CREATE TABLE review_queues (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(text("CREATE TABLE review_queue_items (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO projects VALUES ('project')"))
    connection.execute(text("INSERT INTO review_queues VALUES ('queue')"))
    connection.execute(text("INSERT INTO review_queue_items VALUES ('item')"))
    connection.execute(
        text(
            "CREATE TABLE review_queue_item_events ("
            "id VARCHAR(36) PRIMARY KEY, review_queue_id VARCHAR(36) NOT NULL, "
            "review_queue_item_id VARCHAR(36) NOT NULL, project_id VARCHAR(36) NOT NULL, "
            "client_request_id VARCHAR(36) NOT NULL, event_type VARCHAR(20) NOT NULL, "
            "actor VARCHAR(100) NOT NULL, comment TEXT, assignee VARCHAR(100), "
            "created_at DATETIME NOT NULL, "
            "CONSTRAINT uq_review_queue_item_event_request UNIQUE "
            "(review_queue_item_id, client_request_id), "
            "CONSTRAINT ck_review_queue_item_event_type CHECK "
            "(event_type IN ('comment', 'assign', 'unassign')), "
            "FOREIGN KEY(review_queue_id) REFERENCES review_queues(id) ON DELETE CASCADE, "
            "FOREIGN KEY(review_queue_item_id) REFERENCES review_queue_items(id) "
            "ON DELETE CASCADE, "
            "FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX ix_review_queue_item_events_item_created "
            "ON review_queue_item_events(review_queue_item_id, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX ix_review_queue_item_events_queue_created "
            "ON review_queue_item_events(review_queue_id, created_at)"
        )
    )
    _insert(connection, "original", "comment")


def _insert(
    connection, event_id: str, event_type: str, request_id: str | None = None
) -> None:
    connection.execute(
        text(
            "INSERT INTO review_queue_item_events "
            "(id, review_queue_id, review_queue_item_id, project_id, "
            "client_request_id, event_type, actor, comment, created_at) "
            "VALUES (:id, 'queue', 'item', 'project', :request, :type, "
            "'researcher', 'preserve comment', '2026-10-24')"
        ),
        {"id": event_id, "request": request_id or event_id, "type": event_type},
    )


def _assert_indexes(connection) -> None:
    indexes = {
        row[0]
        for row in connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='review_queue_item_events'"
            )
        )
    }
    assert "ix_review_queue_item_events_item_created" in indexes
    assert "ix_review_queue_item_events_queue_created" in indexes


def test_upgrade_preserves_coordination_and_accepts_server_triage(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_schema(connection)
        migration = _migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.scalar(
            text("SELECT comment FROM review_queue_item_events WHERE id='original'")
        ) == "preserve comment"
        _assert_indexes(connection)
        for action in ("triage_start", "triage_skip", "triage_return"):
            _insert(connection, action, action)
        with pytest.raises(IntegrityError):
            _insert(connection, "unknown", "triage_accept")
        with pytest.raises(IntegrityError):
            _insert(connection, "duplicate", "triage_skip")
            _insert(connection, "duplicate-other", "triage_skip", request_id="duplicate")
        assert connection.scalar(
            text("SELECT COUNT(*) FROM review_queue_item_events")
        ) == 5
        assert connection.scalar(text("PRAGMA foreign_key_check")) is None
    engine.dispose()


def test_downgrade_refuses_to_destroy_triage_history(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_schema(connection)
        migration = _migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        _insert(connection, "triaged", "triage_skip")
        with pytest.raises(RuntimeError, match="Cannot downgrade QC triage audit schema"):
            migration.downgrade()
        assert connection.scalar(
            text("SELECT event_type FROM review_queue_item_events WHERE id='triaged'")
        ) == "triage_skip"
        connection.execute(text("DELETE FROM review_queue_item_events WHERE id='triaged'"))
        migration.downgrade()
        _assert_indexes(connection)
        assert connection.scalar(
            text("SELECT comment FROM review_queue_item_events WHERE id='original'")
        ) == "preserve comment"
        with pytest.raises(IntegrityError):
            _insert(connection, "not-allowed", "triage_start")
    engine.dispose()
