"""Reject forged review-lineage stamps without the 0038 event primary key.

The idempotency UNIQUE constraint alone does not enforce globally unique
review event IDs across distinct review items. Preflight must remain read-only.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
@pytest.mark.parametrize("primary_key", ["missing", "composite", "correct"])
def test_review_event_primary_key_preserves_scientific_and_qc_records(
    revision: str, primary_key: str
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )
            connection.execute(text("CREATE TABLE observations (value TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO observations VALUES ('coral observation')"))
            allowed = ["comment", "assign", "unassign"]
            if revision != "0038":
                allowed.extend(["triage_start", "triage_skip", "triage_return"])
            if revision == "0040":
                allowed.append("triage_complete")
            check_values = ", ".join(f"'{event_type}'" for event_type in allowed)
            id_column = (
                "id TEXT NOT NULL PRIMARY KEY"
                if primary_key == "correct"
                else "id TEXT NOT NULL"
            )
            composite = (
                ", PRIMARY KEY (id, review_queue_id)" if primary_key == "composite" else ""
            )
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    f"{id_column}, "
                    "review_queue_id TEXT NOT NULL, "
                    "review_queue_item_id TEXT NOT NULL, "
                    "project_id TEXT NOT NULL, "
                    "client_request_id TEXT NOT NULL, "
                    "event_type TEXT NOT NULL, "
                    "actor TEXT NOT NULL, "
                    "comment TEXT, assignee TEXT, created_at TEXT NOT NULL, "
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    "CONSTRAINT ck_review_queue_item_event_type "
                    f"CHECK (event_type IN ({check_values}))"
                    f"{composite})"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events "
                    "(id, review_queue_id, review_queue_item_id, project_id, "
                    "client_request_id, event_type, actor, created_at) "
                    "VALUES ('event-1', 'queue-1', 'item-1', 'project-1', "
                    "'request-1', 'comment', 'researcher', '2026-11-05')"
                )
            )
            # A per-item request UNIQUE constraint does not protect global
            # event identity: an event ID can be reused for another item when
            # the global primary key is absent. Exercise that actual failure
            # mode, not merely the inspector's reported schema metadata.
            if primary_key == "missing":
                connection.execute(
                    text(
                        "INSERT INTO review_queue_item_events "
                        "(id, review_queue_id, review_queue_item_id, project_id, "
                        "client_request_id, event_type, actor, created_at) "
                        "VALUES ('event-1', 'queue-1', 'item-2', 'project-1', "
                        "'request-2', 'comment', 'researcher', '2026-11-05')"
                    )
                )
                assert connection.scalar(
                    text("SELECT COUNT(*) FROM review_queue_item_events WHERE id = 'event-1'")
                ) == 2
            schema_before = tuple(
                connection.execute(
                    text("SELECT name, sql FROM sqlite_master ORDER BY name")
                ).all()
            )
            events_before = tuple(
                connection.execute(text("SELECT * FROM review_queue_item_events")).all()
            )
            for _ in range(2):
                if primary_key == "correct":
                    assert_compatible_revision_0038(connection)
                else:
                    with pytest.raises(RuntimeError, match="primary key must be exactly id"):
                        assert_compatible_revision_0038(connection)
                assert tuple(
                    connection.execute(
                        text("SELECT name, sql FROM sqlite_master ORDER BY name")
                    ).all()
                ) == schema_before
                assert tuple(
                    connection.execute(text("SELECT * FROM review_queue_item_events")).all()
                ) == events_before
                assert connection.scalar(text("SELECT value FROM observations")) == (
                    "coral observation"
                )
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    revision
                )
    finally:
        engine.dispose()
