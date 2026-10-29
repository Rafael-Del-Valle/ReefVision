"""Fail closed when a forged 0041 stamp permits anonymous QC audit events.

SQLite accepts NULL in a CHECK and in some noninteger PRIMARY KEY schemas.
A persisted human-review event must retain explicit identity, scope, actor,
and timestamp even when its event-type allowlist and idempotency key are valid.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

_ATTRIBUTION_FIELDS = ("id", "review_queue_id", "project_id", "actor", "created_at")
_EVENT_TYPES = (
    "'comment', 'assign', 'unassign', 'triage_start', "
    "'triage_skip', 'triage_return', 'triage_complete'"
)


@pytest.mark.parametrize("nullable_field", [None, *_ATTRIBUTION_FIELDS])
def test_0041_rejects_nullable_audit_attribution_without_mutating_records(
    nullable_field: str | None,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
            connection.execute(text("CREATE TABLE observations (value TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO observations VALUES ('original coral observation')")
            )

            required = (
                "id",
                "review_queue_id",
                "review_queue_item_id",
                "project_id",
                "client_request_id",
                "event_type",
                "actor",
                "created_at",
            )
            fields = [
                f"{name} TEXT" + ("" if name == nullable_field else " NOT NULL")
                + (" PRIMARY KEY" if name == "id" else "")
                for name in required
            ]
            fields.extend(
                [
                    "comment TEXT",
                    "assignee TEXT",
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id)",
                    "CONSTRAINT ck_review_queue_item_event_type "
                    f"CHECK (event_type IN ({_EVENT_TYPES}))",
                ]
            )
            connection.execute(text(f"CREATE TABLE review_queue_item_events ({', '.join(fields)})"))
            connection.execute(
                text(
                    "CREATE TABLE review_queue_bulk_requests ("
                    "id TEXT NOT NULL PRIMARY KEY, "
                    "review_queue_id TEXT NOT NULL, project_id TEXT NOT NULL, "
                    "action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT, "
                    "item_ids_json TEXT NOT NULL, created_at TEXT NOT NULL, "
                    "FOREIGN KEY(review_queue_id) REFERENCES review_queues(id) ON DELETE RESTRICT, "
                    "FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE RESTRICT)"
                )
            )
            event = {
                "id": "event-1",
                "review_queue_id": "queue-1",
                "review_queue_item_id": "item-1",
                "project_id": "project-1",
                "client_request_id": "request-1",
                "event_type": "comment",
                "actor": "researcher",
                "created_at": "2026-10-29T00:00:00Z",
            }
            if nullable_field is not None:
                event[nullable_field] = None
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events "
                    "(id, review_queue_id, review_queue_item_id, project_id, "
                    "client_request_id, event_type, actor, created_at) "
                    "VALUES (:id, :review_queue_id, :review_queue_item_id, "
                    ":project_id, :client_request_id, :event_type, :actor, :created_at)"
                ),
                event,
            )
            schema_before = tuple(
                connection.execute(
                    text("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
                ).all()
            )
            events_before = tuple(
                connection.execute(
                    text(
                        "SELECT id, review_queue_id, project_id, actor, created_at "
                        "FROM review_queue_item_events"
                    )
                ).all()
            )
            for _ in range(2):
                if nullable_field is None:
                    assert_compatible_revision_0038(connection)
                else:
                    with pytest.raises(
                        RuntimeError, match="nullable review-event attribution fields"
                    ):
                        assert_compatible_revision_0038(connection)
                assert (
                    tuple(
                        connection.execute(
                            text(
                                "SELECT name, sql FROM sqlite_master "
                                "WHERE type='table' ORDER BY name"
                            )
                        ).all()
                    )
                    == schema_before
                )
                assert (
                    tuple(
                        connection.execute(
                            text(
                                "SELECT id, review_queue_id, project_id, actor, created_at "
                                "FROM review_queue_item_events"
                            )
                        ).all()
                    )
                    == events_before
                )
                assert connection.scalar(text("SELECT value FROM observations")) == (
                    "original coral observation"
                )
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
    finally:
        engine.dispose()
