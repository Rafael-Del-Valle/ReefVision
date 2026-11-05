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


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
@pytest.mark.parametrize("nullable_field", ["review_queue_item_id", "client_request_id"])
def test_earlier_review_revision_rejects_nullable_request_identity_with_unique_key(
    revision: str, nullable_field: str
) -> None:
    """SQLite UNIQUE permits NULL; a stamped earlier QC revision must not."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
            connection.execute(text("CREATE TABLE observations (value TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO observations VALUES ('preserved biological observation')")
            )
            allowed = ["comment", "assign", "unassign"]
            if revision in {"0039", "0040"}:
                allowed.extend(["triage_start", "triage_skip", "triage_return"])
            if revision == "0040":
                allowed.append("triage_complete")
            check = ", ".join(f"'{event}'" for event in allowed)
            identity = {
                field: f"{field} TEXT"
                + ("" if field == nullable_field else " NOT NULL")
                for field in ("review_queue_item_id", "client_request_id")
            }
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT NOT NULL PRIMARY KEY, "
                    "review_queue_id TEXT NOT NULL, "
                    f"{identity['review_queue_item_id']}, "
                    "project_id TEXT NOT NULL, "
                    f"{identity['client_request_id']}, "
                    "event_type TEXT NOT NULL, actor TEXT NOT NULL, "
                    "comment TEXT, assignee TEXT, created_at TEXT NOT NULL, "
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    f"CONSTRAINT ck_review_queue_item_event_type CHECK (event_type IN ({check})))"
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
            before = tuple(
                connection.execute(text("SELECT * FROM review_queue_item_events")).all()
            )
            for _ in range(2):
                with pytest.raises(RuntimeError, match="nullable review-event idempotency"):
                    assert_compatible_revision_0038(connection)
                assert tuple(
                    connection.execute(text("SELECT * FROM review_queue_item_events")).all()
                ) == before
                assert connection.scalar(text("SELECT value FROM observations")) == (
                    "preserved biological observation"
                )
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
    finally:
        engine.dispose()
