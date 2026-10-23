"""Safety regressions for colliding ReefVision 1.1/1.6 Alembic 0038 IDs."""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


REVIEW_SCHEMA = (
    "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
    "project_id TEXT, client_request_id TEXT, event_type TEXT, actor TEXT, "
    "comment TEXT, assignee TEXT, created_at TEXT"
)


@pytest.mark.parametrize("revision", [None, "0037", "0039"])
def test_fresh_and_noncolliding_revisions_are_not_modified(revision: str | None) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('scientific observation')"))
        if revision is not None:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
            )
        assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "scientific observation"


def test_review_lineage_0038_is_accepted_without_writes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
        connection.execute(text(f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA})"))
        connection.execute(
            text("INSERT INTO review_queue_item_events (id) VALUES ('event-preserved')")
        )
        assert_compatible_revision_0038(connection)
        assert (
            connection.scalar(text("SELECT id FROM review_queue_item_events"))
            == "event-preserved"
        )


@pytest.mark.parametrize(
    "tables",
    [
        (),
        ("scientific_records",),
        ("environmental_cache_entries",),
        ("scientific_records", "environmental_cache_entries"),
        ("review_queue_item_events", "scientific_records"),
        ("review_queue_item_events", "environmental_cache_entries"),
    ],
)
def test_colliding_0038_rejected_without_mutating_assets(tables: tuple[str, ...]) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('do not delete')"))
        for table in tables:
            schema = REVIEW_SCHEMA if table == "review_queue_item_events" else "id TEXT PRIMARY KEY"
            connection.execute(text(f"CREATE TABLE {table} ({schema})"))
        with pytest.raises(RuntimeError, match="Unsafe ReefVision Alembic revision 0038 collision"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "do not delete"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
        for table in tables:
            assert connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).scalar() == table


def test_colliding_0038_rejects_incomplete_review_table() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
        connection.execute(text("CREATE TABLE review_queue_item_events (id TEXT PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="missing review columns"):
            assert_compatible_revision_0038(connection)
