"""Safety regressions for colliding ReefVision 1.1/1.6 Alembic 0038 IDs."""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

REVIEW_SCHEMA = (
    "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
    "project_id TEXT, client_request_id TEXT, event_type TEXT, actor TEXT, "
    "comment TEXT, assignee TEXT, created_at TEXT"
)


@pytest.mark.parametrize("revision", [None, "0037"])
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


@pytest.mark.parametrize("revision", ["0038", "0039"])
def test_review_lineage_is_accepted_without_writes(revision: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
        )
        check = (
            ", CONSTRAINT ck_review_queue_item_event_type "
            "CHECK (event_type IN ('comment', 'assign', 'unassign', "
            "'triage_start', 'triage_skip', 'triage_return'))"
            if revision == "0039"
            else ""
        )
        connection.execute(text(f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}{check})"))
        connection.execute(
            text("INSERT INTO review_queue_item_events (id) VALUES ('event-preserved')")
        )
        assert_compatible_revision_0038(connection)
        assert (
            connection.scalar(text("SELECT id FROM review_queue_item_events")) == "event-preserved"
        )


@pytest.mark.parametrize("revision", ["0038", "0039"])
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
def test_colliding_review_revision_rejected_without_mutating_assets(
    tables: tuple[str, ...], revision: str
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
        )
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('do not delete')"))
        for table in tables:
            schema = REVIEW_SCHEMA if table == "review_queue_item_events" else "id TEXT PRIMARY KEY"
            connection.execute(text(f"CREATE TABLE {table} ({schema})"))
        expected_error = f"Unsafe ReefVision Alembic revision {revision} collision"
        with pytest.raises(RuntimeError, match=expected_error):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "do not delete"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        for table in tables:
            assert (
                connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).scalar()
                == table
            )


@pytest.mark.parametrize("revision", ["0038", "0039"])
def test_colliding_review_revision_rejects_incomplete_review_table(revision: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
        )
        connection.execute(text("CREATE TABLE review_queue_item_events (id TEXT PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="missing review columns"):
            assert_compatible_revision_0038(connection)


@pytest.mark.parametrize(
    ("revision", "supports_triage", "should_reject"),
    [
        ("0038", False, False),
        ("0039", False, True),
        ("0039", True, False),
    ],
)
def test_revision_0039_rejects_obsolete_event_check_without_writes(
    revision: str, supports_triage: bool, should_reject: bool
) -> None:
    """Do not trust a 0039 stamp if SQLite still has the 0038 event constraint."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    allowed = "'comment', 'assign', 'unassign'"
    if supports_triage:
        allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
        )
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type) "
                "VALUES ('preserved-event', 'comment')"
            )
        )
        if should_reject:
            with pytest.raises(RuntimeError, match=r"obsolete|still excludes"):
                assert_compatible_revision_0038(connection)
        else:
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert (
            connection.scalar(text("SELECT id FROM review_queue_item_events")) == "preserved-event"
        )

@pytest.mark.parametrize(
    ("revision", "constraint_name", "should_reject"),
    [
        ("0038", None, False),
        ("0039", None, True),
        ("0039", "renamed_event_type_check", True),
        ("0039", "ck_review_queue_item_event_type", False),
    ],
)
def test_revision_0039_requires_named_triage_check_without_writes(
    revision: str, constraint_name: str | None, should_reject: bool
) -> None:
    """An already-at-head database must not silently lose audit constraints."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
        )
        check = (
            f", CONSTRAINT {constraint_name} CHECK (event_type IN "
            "('comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return'))"
            if constraint_name is not None
            else ""
        )
        connection.execute(text(f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}{check})"))
        connection.execute(
            text("INSERT INTO review_queue_item_events (id) VALUES ('preserve-event')")
        )
        if should_reject:
            with pytest.raises(RuntimeError, match="missing or renamed"):
                assert_compatible_revision_0038(connection)
        else:
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert (
            connection.scalar(text("SELECT id FROM review_queue_item_events")) == "preserve-event"
        )

_VALID_EVENT_TYPES = (
    "'comment', 'assign', 'unassign', 'triage_start', "
    "'triage_skip', 'triage_return'"
)


@pytest.mark.parametrize(
    "expression",
    [
        f"event_type IN ({_VALID_EVENT_TYPES}) OR 1=1",
        f"event_type IN ({_VALID_EVENT_TYPES}, 'unreviewed')",
        "event_type IN ('triage_start', 'triage_skip', 'triage_return')",
    ],
)
def test_revision_0039_rejects_permissive_event_checks_without_writes(
    expression: str,
) -> None:
    """A 0039 stamp must not accept arbitrary or incomplete event types."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0039')"))
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}, "
                f"CONSTRAINT ck_review_queue_item_event_type CHECK ({expression}))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type) "
                "VALUES ('preserved-event', 'triage_start')"
            )
        )
        schema_before = connection.scalar(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='review_queue_item_events'"
            )
        )
        with pytest.raises(RuntimeError, match="permits unsupported|still excludes"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0039"
        assert connection.scalar(text("SELECT id FROM review_queue_item_events")) == "preserved-event"
        assert connection.scalar(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='review_queue_item_events'"
            )
        ) == schema_before
