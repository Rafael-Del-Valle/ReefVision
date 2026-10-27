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
    connection.execute(
        text(
            "CREATE TABLE review_queues "
            "(id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NOT NULL)"
        )
    )
    connection.execute(
        text(
            "CREATE TABLE review_queue_items "
            "(id VARCHAR(36) PRIMARY KEY, review_queue_id VARCHAR(36) NOT NULL, "
            "project_id VARCHAR(36) NOT NULL)"
        )
    )
    connection.execute(text("INSERT INTO projects VALUES ('project')"))
    connection.execute(text("INSERT INTO projects VALUES ('other_project')"))
    connection.execute(text("INSERT INTO review_queues VALUES ('queue', 'project')"))
    connection.execute(text("INSERT INTO review_queues VALUES ('other_queue', 'other_project')"))
    connection.execute(text("INSERT INTO review_queue_items VALUES ('item', 'queue', 'project')"))
    connection.execute(
        text("INSERT INTO review_queue_items VALUES ('other_item', 'other_queue', 'other_project')")
    )
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


def _insert(connection, event_id: str, event_type: str, request_id: str | None = None) -> None:
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
        assert (
            connection.scalar(
                text("SELECT comment FROM review_queue_item_events WHERE id='original'")
            )
            == "preserve comment"
        )
        _assert_indexes(connection)
        for action in ("triage_start", "triage_skip", "triage_return"):
            _insert(connection, action, action)
        with pytest.raises(IntegrityError):
            _insert(connection, "unknown", "triage_accept")
        with pytest.raises(IntegrityError):
            _insert(connection, "duplicate", "triage_skip")
            _insert(connection, "duplicate-other", "triage_skip", request_id="duplicate")
        assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_item_events")) == 5
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
        assert (
            connection.scalar(
                text("SELECT event_type FROM review_queue_item_events WHERE id='triaged'")
            )
            == "triage_skip"
        )
        connection.execute(text("DELETE FROM review_queue_item_events WHERE id='triaged'"))
        migration.downgrade()
        _assert_indexes(connection)
        assert (
            connection.scalar(
                text("SELECT comment FROM review_queue_item_events WHERE id='original'")
            )
            == "preserve comment"
        )
        with pytest.raises(IntegrityError):
            _insert(connection, "not-allowed", "triage_start")
    engine.dispose()


@pytest.mark.parametrize(
    ("parent_column", "parent_id"),
    [
        ("review_queue_id", "queue"),
        ("review_queue_item_id", "item"),
        ("project_id", "project"),
    ],
)
def test_upgrade_refuses_orphan_audit_events_without_rewriting(
    monkeypatch, parent_column: str, parent_id: str
) -> None:
    # Historical SQLite connections could disable FK enforcement.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_schema(connection)
        migration = _migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        connection.execute(
            text(
                f"UPDATE review_queue_item_events SET {parent_column}='missing' WHERE id='original'"
            )
        )
        with pytest.raises(RuntimeError, match="orphan review events"):
            migration.upgrade()
        assert (
            connection.scalar(
                text("SELECT COUNT(*) FROM review_queue_item_events WHERE id='original'")
            )
            == 1
        )
        with pytest.raises(IntegrityError):
            _insert(connection, "triage-before-repair", "triage_start")
        connection.execute(
            text(
                f"UPDATE review_queue_item_events SET {parent_column}=:parent WHERE id='original'"
            ),
            {"parent": parent_id},
        )
        migration.upgrade()
        _insert(connection, "triage-after-repair", "triage_start")
        assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_item_events")) == 2
    engine.dispose()


@pytest.mark.parametrize(
    ("invalid_scope", "repaired_scope"),
    [
        ("review_queue_id='other_queue'", "review_queue_id='queue'"),
        ("review_queue_item_id='other_item'", "review_queue_item_id='item'"),
        ("project_id='other_project'", "project_id='project'"),
        (
            "review_queue_id='other_queue', review_queue_item_id='other_item'",
            "review_queue_id='queue', review_queue_item_id='item'",
        ),
    ],
)
def test_upgrade_refuses_cross_scoped_audit_events_with_existing_parents(
    monkeypatch, invalid_scope: str, repaired_scope: str
) -> None:
    # Every FK target exists, but the event's queue/item/project disagree.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _legacy_schema(connection)
        migration = _migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        connection.execute(
            text(f"UPDATE review_queue_item_events SET {invalid_scope} WHERE id='original'")
        )
        with pytest.raises(RuntimeError, match="repair parent references and scope"):
            migration.upgrade()
        assert (
            connection.scalar(
                text("SELECT comment FROM review_queue_item_events WHERE id='original'")
            )
            == "preserve comment"
        )
        with pytest.raises(IntegrityError):
            _insert(connection, "triage-before-scope-repair", "triage_start")
        connection.execute(
            text(f"UPDATE review_queue_item_events SET {repaired_scope} WHERE id='original'")
        )
        migration.upgrade()
        _insert(connection, "triage-after-scope-repair", "triage_start")
        assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_item_events")) == 2
    engine.dispose()


def test_file_backed_upgrade_and_downgrade_preserve_audit_foreign_keys(
    monkeypatch, tmp_path: Path
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'review-audit.sqlite'}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        with connection.begin():
            _legacy_schema(connection)
            migration = _migration()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            _insert(connection, "triaged", "triage_skip")
            references = {
                (row[3], row[2], row[6])
                for row in connection.exec_driver_sql(
                    "PRAGMA foreign_key_list(review_queue_item_events)"
                )
            }
            assert references == {
                ("review_queue_id", "review_queues", "CASCADE"),
                ("review_queue_item_id", "review_queue_items", "CASCADE"),
                ("project_id", "projects", "CASCADE"),
            }
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "UPDATE review_queue_item_events SET project_id='missing' "
                        "WHERE id='triaged'"
                    )
                )
    with engine.begin() as connection:
        assert (
            connection.scalar(
                text("SELECT event_type FROM review_queue_item_events WHERE id='triaged'")
            )
            == "triage_skip"
        )
        migration = _migration()
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        with pytest.raises(RuntimeError, match="Cannot downgrade QC triage audit schema"):
            migration.downgrade()
        connection.execute(text("DELETE FROM review_queue_item_events WHERE id='triaged'"))
        migration.downgrade()
        _assert_indexes(connection)
        assert {
            (row[3], row[2], row[6])
            for row in connection.exec_driver_sql(
                "PRAGMA foreign_key_list(review_queue_item_events)"
            )
        } == {
            ("review_queue_id", "review_queues", "CASCADE"),
            ("review_queue_item_id", "review_queue_items", "CASCADE"),
            ("project_id", "projects", "CASCADE"),
        }
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT comment FROM review_queue_item_events WHERE id='original'")
            )
            == "preserve comment"
        )
        with pytest.raises(IntegrityError):
            _insert(connection, "triage-after-downgrade", "triage_start")
    engine.dispose()
