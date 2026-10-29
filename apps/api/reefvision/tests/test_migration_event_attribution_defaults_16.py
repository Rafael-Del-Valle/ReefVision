"""Reject forged QC audit defaults without changing scientific or reviewer records.

The real 0038 review-event migration requires explicit reviewer, scope,
request, and timestamp fields. A forged revision marker must not allow SQLite
to invent scientific-review provenance when a caller omits those fields.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

_AUDIT_FIELDS = (
    "id",
    "review_queue_id",
    "review_queue_item_id",
    "project_id",
    "client_request_id",
    "actor",
    "created_at",
)


@pytest.mark.parametrize("revision", ["0038", "0041"])
@pytest.mark.parametrize("defaulted_field", [None, *_AUDIT_FIELDS])
def test_review_event_attribution_defaults_fail_closed_without_writes(
    revision: str, defaulted_field: str | None
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
            connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO preserved VALUES ('original coral observation')")
            )
            fields = [
                f"{name} TEXT NOT NULL"
                + (" PRIMARY KEY" if name == "id" else "")
                + (" DEFAULT 'fabricated'" if name == defaulted_field else "")
                for name in _AUDIT_FIELDS
            ]
            fields.extend(["event_type TEXT NOT NULL", "comment TEXT", "assignee TEXT"])
            allowed = "'comment', 'assign', 'unassign'"
            if revision == "0041":
                allowed += (
                    ", 'triage_start', 'triage_skip', 'triage_return', "
                    "'triage_complete'"
                )
            fields.append(
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed}))"
            )
            fields.append(
                "CONSTRAINT uq_review_queue_item_event_request "
                "UNIQUE (review_queue_item_id, client_request_id)"
            )
            connection.execute(
                text(f"CREATE TABLE review_queue_item_events ({', '.join(fields)})")
            )
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events "
                    "(id, review_queue_id, review_queue_item_id, project_id, "
                    "client_request_id, actor, created_at, event_type) VALUES "
                    "('event-1', 'queue-1', 'item-1', 'project-1', 'request-1', "
                    "'researcher', '2026-10-29T00:00:00', 'comment')"
                )
            )
            if revision == "0041":
                connection.execute(
                    text(
                        "CREATE TABLE review_queue_bulk_requests ("
                        "id TEXT NOT NULL PRIMARY KEY, "
                        "review_queue_id TEXT NOT NULL, project_id TEXT NOT NULL, "
                        "action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT, "
                        "item_ids_json TEXT NOT NULL, created_at TEXT NOT NULL, "
                        "FOREIGN KEY(review_queue_id) "
                        "REFERENCES review_queues(id) ON DELETE RESTRICT, "
                        "FOREIGN KEY(project_id) "
                        "REFERENCES projects(id) ON DELETE RESTRICT)"
                    )
                )
            original_schema = tuple(
                connection.execute(
                    text(
                        "SELECT name, sql FROM sqlite_master "
                        "WHERE type='table' ORDER BY name"
                    )
                ).all()
            )
            original_events = tuple(
                connection.execute(
                    text(
                        "SELECT id, actor, client_request_id, created_at "
                        "FROM review_queue_item_events"
                    )
                ).all()
            )
            for _ in range(2):
                if defaulted_field is None:
                    assert_compatible_revision_0038(connection)
                else:
                    with pytest.raises(
                        RuntimeError, match="unexpected server defaults"
                    ):
                        assert_compatible_revision_0038(connection)
                assert tuple(
                    connection.execute(
                        text(
                            "SELECT name, sql FROM sqlite_master "
                            "WHERE type='table' ORDER BY name"
                        )
                    ).all()
                ) == original_schema
                assert tuple(
                    connection.execute(
                        text(
                            "SELECT id, actor, client_request_id, created_at "
                            "FROM review_queue_item_events"
                        )
                    ).all()
                ) == original_events
                assert connection.scalar(text("SELECT value FROM preserved")) == (
                    "original coral observation"
                )
                assert connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                ) == revision
    finally:
        engine.dispose()
