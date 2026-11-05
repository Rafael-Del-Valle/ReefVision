"""Ensure QC CHECK validation distinguishes SQL keyword case from event-value case."""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.mark.parametrize("uppercase_literals", [False, True])
@pytest.mark.parametrize("uppercase_keywords", [False, True])
def test_review_event_check_literals_are_case_sensitive(
    uppercase_literals: bool, uppercase_keywords: bool
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
            connection.execute(text("CREATE TABLE observations (value TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO observations VALUES ('coral observation')"))
            if uppercase_literals:
                values = ("COMMENT", "ASSIGN", "UNASSIGN")
            else:
                values = ("comment", "assign", "unassign")
            keyword = "IN" if uppercase_keywords else "in"
            identifier = "EVENT_TYPE" if uppercase_keywords else "event_type"
            check = f"{identifier} {keyword} ({', '.join(repr(value) for value in values)})"
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT NOT NULL PRIMARY KEY, "
                    "review_queue_id TEXT NOT NULL, "
                    "review_queue_item_id TEXT NOT NULL, "
                    "project_id TEXT NOT NULL, "
                    "client_request_id TEXT NOT NULL, "
                    "event_type TEXT NOT NULL, actor TEXT NOT NULL, "
                    "comment TEXT, assignee TEXT, created_at TEXT NOT NULL, "
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    "CONSTRAINT ck_review_queue_item_event_type "
                    f"CHECK ({check}))"
                )
            )
            before = tuple(
                connection.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()
            )
            for _ in range(2):
                if uppercase_literals:
                    with pytest.raises(RuntimeError, match="CHECK constraint"):
                        assert_compatible_revision_0038(connection)
                else:
                    assert_compatible_revision_0038(connection)
                assert (
                    tuple(
                        connection.execute(
                            text("SELECT name, sql FROM sqlite_master ORDER BY name")
                        ).all()
                    )
                    == before
                )
                assert (
                    connection.scalar(text("SELECT value FROM observations")) == "coral observation"
                )
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
    finally:
        engine.dispose()
