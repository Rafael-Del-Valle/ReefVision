"""Guard earlier 1.6 review revisions against missing audit replay identity."""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
def test_earlier_review_revision_rejects_missing_event_request_uniqueness(
    revision: str,
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
            allowed = ["comment", "assign", "unassign"]
            if revision in {"0039", "0040"}:
                allowed += ["triage_start", "triage_skip", "triage_return"]
            if revision == "0040":
                allowed.append("triage_complete")
            check = ", ".join(f"'{event}'" for event in allowed)
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT NOT NULL PRIMARY KEY, "
                    "review_queue_id TEXT NOT NULL, "
                    "review_queue_item_id TEXT NOT NULL, "
                    "project_id TEXT NOT NULL, "
                    "client_request_id TEXT NOT NULL, "
                    "event_type TEXT NOT NULL, "
                    "actor TEXT NOT NULL, comment TEXT, assignee TEXT, "
                    "created_at TEXT NOT NULL, "
                    f"CONSTRAINT ck_review_queue_item_event_type CHECK (event_type IN ({check})))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events VALUES ("
                    "'event-1', 'queue-1', 'item-1', 'project-1', 'request-1', "
                    "'comment', 'researcher', 'observed', NULL, '2026-11-04')"
                )
            )
            before = connection.execute(
                text("SELECT * FROM review_queue_item_events")
            ).all()
            with pytest.raises(RuntimeError, match="idempotency UNIQUE constraint"):
                assert_compatible_revision_0038(connection)
            assert connection.execute(
                text("SELECT * FROM review_queue_item_events")
            ).all() == before
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
            )
    finally:
        engine.dispose()
