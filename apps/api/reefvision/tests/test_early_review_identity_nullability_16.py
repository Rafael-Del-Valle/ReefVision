"""Regression for early 1.6 QC revision request-key nullability.

SQLite UNIQUE permits repeated NULL values. A forged 0038-0040 stamp with
nullable request identity must be rejected before desktop migrations write.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
@pytest.mark.parametrize("nullable_field", ["review_queue_item_id", "client_request_id"])
def test_early_review_revision_rejects_nullable_request_key_without_writes(
    revision: str, nullable_field: str
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
            connection.execute(text("CREATE TABLE preserved (observation TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO preserved VALUES ('original polyp count')"))
            allowed = "'comment', 'assign', 'unassign'"
            if revision in {"0039", "0040"}:
                allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
            if revision == "0040":
                allowed += ", 'triage_complete'"
            item_null = "" if nullable_field == "review_queue_item_id" else " NOT NULL"
            request_null = "" if nullable_field == "client_request_id" else " NOT NULL"
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                    f"review_queue_item_id TEXT{item_null}, "
                    "project_id TEXT NOT NULL, "
                    f"client_request_id TEXT{request_null}, "
                    "event_type TEXT NOT NULL, actor TEXT NOT NULL, "
                    "comment TEXT, assignee TEXT, created_at TEXT NOT NULL, "
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    "CONSTRAINT ck_review_queue_item_event_type "
                    f"CHECK (event_type IN ({allowed})))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events "
                    "(id, review_queue_id, review_queue_item_id, client_request_id, "
                    "project_id, event_type, actor, created_at) "
                    "VALUES ('existing-event', 'queue-1', 'item-1', 'request-1', "
                    "'project-1', 'comment', "
                    "'researcher-1', '2026-04-03T12:00:00')"
                )
            )
            with pytest.raises(
                RuntimeError,
                match=f"revision {revision} collision: nullable review-event idempotency",
            ):
                assert_compatible_revision_0038(connection)
            assert connection.scalar(text("SELECT observation FROM preserved")) == (
                "original polyp count"
            )
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
            assert connection.scalar(text("SELECT id FROM review_queue_item_events")) == (
                "existing-event"
            )
    finally:
        engine.dispose()
