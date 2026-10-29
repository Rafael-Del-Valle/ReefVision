"""Reject forged revision-0041 bulk registries with synthetic audit defaults.

The real 0041 migration has no server defaults on required identity, reviewer,
scope, or action fields. A forged schema could silently invent attribution even
when its columns, NOT NULL constraints, primary key and foreign keys look valid.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

_REQUIRED_FIELDS = (
    "id",
    "review_queue_id",
    "project_id",
    "action",
    "actor",
    "item_ids_json",
    "created_at",
)
_EVENT_TYPES = (
    "'comment', 'assign', 'unassign', 'triage_start', "
    "'triage_skip', 'triage_return', 'triage_complete'"
)


@pytest.mark.parametrize("defaulted_field", [None, *_REQUIRED_FIELDS])
def test_0041_bulk_registry_defaults_fail_closed_without_writes(
    defaulted_field: str | None,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            )
            connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
            connection.execute(text("CREATE TABLE observations (value TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO observations VALUES ('original coral observation')")
            )
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
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    "CONSTRAINT ck_review_queue_item_event_type "
                    f"CHECK (event_type IN ({_EVENT_TYPES})))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO review_queue_item_events "
                    "(id, review_queue_id, review_queue_item_id, project_id, "
                    "client_request_id, event_type, actor, created_at) VALUES "
                    "('event-1', 'queue-1', 'item-1', 'project-1', 'uuid-1', "
                    "'comment', 'reviewer', '2026-10-29T00:00:00')"
                )
            )
            fields = [
                f"{name} TEXT NOT NULL"
                + (" PRIMARY KEY" if name == "id" else "")
                + (" DEFAULT 'forged'" if name == defaulted_field else "")
                for name in _REQUIRED_FIELDS
            ]
            fields.extend(
                [
                    "reason TEXT",
                    "FOREIGN KEY(review_queue_id) "
                    "REFERENCES review_queues(id) ON DELETE RESTRICT",
                    "FOREIGN KEY(project_id) "
                    "REFERENCES projects(id) ON DELETE RESTRICT",
                ]
            )
            connection.execute(
                text(f"CREATE TABLE review_queue_bulk_requests ({', '.join(fields)})")
            )
            before_schema = tuple(
                connection.execute(
                    text(
                        "SELECT name, sql FROM sqlite_master "
                        "WHERE type='table' ORDER BY name"
                    )
                ).all()
            )
            for _ in range(2):
                if defaulted_field is None:
                    assert_compatible_revision_0038(connection)
                else:
                    with pytest.raises(RuntimeError, match="defaulted required columns"):
                        assert_compatible_revision_0038(connection)
                after_schema = tuple(
                    connection.execute(
                        text(
                            "SELECT name, sql FROM sqlite_master "
                            "WHERE type='table' ORDER BY name"
                        )
                    ).all()
                )
                assert after_schema == before_schema
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0041"
                )
                assert connection.scalar(text("SELECT value FROM observations")) == (
                    "original coral observation"
                )
                assert connection.scalar(
                    text("SELECT actor FROM review_queue_item_events")
                ) == "reviewer"
                assert connection.scalar(
                    text("SELECT COUNT(*) FROM review_queue_bulk_requests")
                ) == 0
    finally:
        engine.dispose()
