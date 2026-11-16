"""Fail closed on extra and generated columns in stamped 1.6 QC audit tables.

A restored table may retain the official column names but add ordinary,
VIRTUAL or STORED generated fields invisible to SQLite table_info.
Do not approve a forged revision merely because required columns survived.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038
from reefvision.tests.review_lineage_fixture_16 import (
    REVIEW_EVENT_FK_SQL,
    install_review_event_history_indexes,
    install_review_event_parent_rows,
)

_EXTRA_COLUMNS = {
    "valid": "",
    "ordinary": ", unexpected_note TEXT",
    "virtual": (
        ", derived_actor TEXT GENERATED ALWAYS AS "
        "(actor || '_derived') VIRTUAL"
    ),
    "stored": (
        ", derived_actor TEXT GENERATED ALWAYS AS "
        "(actor || '_derived') STORED"
    ),
}


def _build_database(path: Path, revision: str, target: str, variant: str) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(
                text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
            connection.execute(text("CREATE TABLE observations (note TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO observations VALUES ('PRIVATE_CORAL_OBSERVATION')")
            )
            install_review_event_parent_rows(connection)
            allowed = "'comment', 'assign', 'unassign'"
            if revision == "0041":
                allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
                allowed += ", 'triage_complete'"
            event_extra = _EXTRA_COLUMNS[variant] if target == "event" else ""
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                    "review_queue_item_id TEXT NOT NULL, project_id TEXT NOT NULL, "
                    "client_request_id TEXT NOT NULL, event_type TEXT NOT NULL, "
                    "actor TEXT NOT NULL, comment TEXT, assignee TEXT, "
                    f"created_at TEXT NOT NULL{event_extra}, "
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    "CONSTRAINT ck_review_queue_item_event_type "
                    f"CHECK (event_type IN ({allowed}))"
                    f"{REVIEW_EVENT_FK_SQL})"
                )
            )
            install_review_event_history_indexes(connection)
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events "
                    "(id, review_queue_id, review_queue_item_id, project_id, "
                    "client_request_id, event_type, actor, comment, created_at) "
                    "VALUES ('event-1', 'queue-1', 'item-1', 'project-1', "
                    "'request-1', 'comment', 'researcher', "
                    "'PRIVATE_REVIEW_NOTE', '2026-11-16')"
                )
            )
            if revision == "0041":
                bulk_extra = _EXTRA_COLUMNS[variant] if target == "bulk" else ""
                connection.execute(
                    text(
                        "CREATE TABLE review_queue_bulk_requests ("
                        "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                        "project_id TEXT NOT NULL, action TEXT NOT NULL, "
                        "actor TEXT NOT NULL, reason TEXT, item_ids_json TEXT NOT NULL, "
                        f"created_at TEXT NOT NULL{bulk_extra}, "
                        "FOREIGN KEY(review_queue_id) REFERENCES review_queues(id) "
                        "ON DELETE RESTRICT, "
                        "FOREIGN KEY(project_id) REFERENCES projects(id) "
                        "ON DELETE RESTRICT)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO review_queue_bulk_requests "
                        "(id, review_queue_id, project_id, action, actor, "
                        "item_ids_json, created_at) VALUES "
                        "('bulk-1', 'queue-1', 'project-1', 'approve', "
                        "'researcher', '[\"item-1\"]', '2026-11-16')"
                    )
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("revision", "target"),
    [("0038", "event"), ("0041", "event"), ("0041", "bulk")],
)
@pytest.mark.parametrize("variant", list(_EXTRA_COLUMNS))
def test_stamped_qc_rejects_unexpected_columns_without_mutating_research(
    tmp_path: Path,
    revision: str,
    target: str,
    variant: str,
) -> None:
    database = tmp_path / "preserved.sqlite"
    _build_database(database, revision, target, variant)
    before_bytes = database.read_bytes()

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.connect() as connection:
            for _ in range(2):
                if variant == "valid":
                    assert_compatible_revision_0038(connection)
                else:
                    expected = (
                        "unexpected review columns"
                        if target == "event"
                        else "unexpected columns"
                    )
                    with pytest.raises(RuntimeError, match=expected) as error:
                        assert_compatible_revision_0038(connection)
                    assert "PRIVATE_" not in str(error.value)
                assert connection.scalar(
                    text("SELECT note FROM observations")
                ) == "PRIVATE_CORAL_OBSERVATION"
                assert connection.execute(
                    text(
                        "SELECT id, actor, comment FROM review_queue_item_events"
                    )
                ).one() == ("event-1", "researcher", "PRIVATE_REVIEW_NOTE")
                if revision == "0041":
                    assert connection.scalar(
                        text("SELECT id FROM review_queue_bulk_requests")
                    ) == "bulk-1"
                assert connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                ) == revision
    finally:
        engine.dispose()

    assert database.read_bytes() == before_bytes
