"""Safety regressions for colliding ReefVision 1.1/1.6 Alembic 0038 IDs."""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

REVIEW_SCHEMA = (
    "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
    "project_id TEXT, client_request_id TEXT, "
    "event_type TEXT NOT NULL, actor TEXT, "
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
        allowed = "'comment', 'assign', 'unassign'"
        if revision == "0039":
            allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
        check = f", CONSTRAINT ck_review_queue_item_event_type CHECK (event_type IN ({allowed}))"
        connection.execute(text(f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}{check})"))
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type) "
                "VALUES ('event-preserved', 'comment')"
            )
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


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
def test_nullable_audit_event_type_rejected_without_mutating_research_data(
    revision: str,
) -> None:
    """SQLite CHECK accepts NULL; a forged revision must not bypass audit typing."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('original observations')"))
        allowed = "'comment', 'assign', 'unassign'"
        if revision in {"0039", "0040"}:
            allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
        if revision == "0040":
            allowed += ", 'triage_complete'"
        # The allowlist is correct but a nullable column makes it ineffective.
        schema = REVIEW_SCHEMA.replace("event_type TEXT NOT NULL", "event_type TEXT")
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({schema}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type) "
                "VALUES ('untyped-event', NULL)"
            )
        )
        with pytest.raises(RuntimeError, match="event_type is nullable"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "original observations"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert connection.scalar(text("SELECT event_type FROM review_queue_item_events")) is None
    engine.dispose()


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
def test_defaulted_audit_event_type_rejected_without_rewriting_history(
    revision: str,
) -> None:
    """An omitted event type must never be silently recorded as a comment."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('original observation')"))
        allowed = "'comment', 'assign', 'unassign'"
        if revision in {"0039", "0040"}:
            allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
        if revision == "0040":
            allowed += ", 'triage_complete'"
        schema = REVIEW_SCHEMA.replace(
            "event_type TEXT NOT NULL",
            "event_type TEXT NOT NULL DEFAULT 'comment'",
        )
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({schema}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        # SQLite accepts an omitted event type because of the forged default.
        connection.execute(
            text("INSERT INTO review_queue_item_events (id) VALUES ('forged-comment')")
        )
        with pytest.raises(RuntimeError, match="unexpected server default"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "original observation"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert (
            connection.scalar(text("SELECT event_type FROM review_queue_item_events")) == "comment"
        )
    engine.dispose()


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
        ("0038", None, True),
        ("0038", "renamed_event_type_check", True),
        ("0038", "ck_review_queue_item_event_type", False),
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
        allowed = "'comment', 'assign', 'unassign'"
        if revision == "0039":
            allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
        check = (
            f", CONSTRAINT {constraint_name} CHECK (event_type IN ({allowed}))"
            if constraint_name is not None
            else ""
        )
        connection.execute(text(f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}{check})"))
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type) "
                "VALUES ('preserve-event', 'comment')"
            )
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
    "'comment', 'assign', 'unassign', 'triage_start', 'triage_skip', 'triage_return'"
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
        with pytest.raises(RuntimeError, match="still excludes"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0039"
        assert (
            connection.scalar(text("SELECT id FROM review_queue_item_events")) == "preserved-event"
        )
        assert (
            connection.scalar(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='review_queue_item_events'"
                )
            )
            == schema_before
        )


@pytest.mark.parametrize(
    ("allowed", "should_reject"),
    [
        (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete'",
            False,
        ),
        (
            "'comment', 'assign', 'unassign', 'triage_start', 'triage_skip', 'triage_return'",
            True,
        ),
        (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete', 'triage_approve'",
            True,
        ),
    ],
)
def test_revision_0040_requires_exact_completion_check_without_writes(
    allowed: str, should_reject: bool
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0040')"))
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('research assets')"))
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        if should_reject:
            with pytest.raises(RuntimeError, match="still excludes"):
                assert_compatible_revision_0038(connection)
        else:
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "research assets"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0040"
    engine.dispose()


@pytest.mark.parametrize(
    "revisions",
    [
        ("0038", "0039"),
        ("0038", "0040"),
        ("0039", "0040"),
        ("0038", "0037"),
        ("0040", "science_v11"),
        ("0038", "0038"),
        ("0039", "0039"),
        ("0040", "0040"),
    ],
)
def test_concurrent_review_heads_fail_closed_without_modifying_research_assets(
    revisions: tuple[str, str],
) -> None:
    """Reject foreign, distinct or duplicate review stamps without touching data."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('original research assets')"))
        with pytest.raises(RuntimeError, match="concurrent review revisions") as exc_info:
            assert_compatible_revision_0038(connection)
        assert str(sorted(revisions)) in str(exc_info.value)
        assert connection.scalar(text("SELECT value FROM preserved")) == "original research assets"
        assert (
            tuple(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            == revisions
        )
    engine.dispose()


_REVIEW_QUEUE_FK = ", FOREIGN KEY(review_queue_id) REFERENCES review_queues(id) ON DELETE RESTRICT"
_PROJECT_FK = ", FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE RESTRICT"
_REVIEW_REQUEST_SCHEMA = REVIEW_SCHEMA.replace(
    "review_queue_item_id TEXT", "review_queue_item_id TEXT NOT NULL"
).replace("client_request_id TEXT", "client_request_id TEXT NOT NULL")


def test_revision_0041_requires_global_bulk_request_registry() -> None:
    """A forged 0041 stamp must never bypass the global request-ID constraint."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
        allowed = (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete'"
        )
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({_REVIEW_REQUEST_SCHEMA}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})), "
                "CONSTRAINT uq_review_queue_item_event_request "
                "UNIQUE (review_queue_item_id, client_request_id))"
            )
        )
        with pytest.raises(RuntimeError, match="bulk request registry"):
            assert_compatible_revision_0038(connection)
        connection.execute(
            text(
                "CREATE TABLE review_queue_bulk_requests ("
                "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "project_id TEXT NOT NULL, action TEXT NOT NULL, "
                "actor TEXT NOT NULL, reason TEXT, item_ids_json TEXT NOT NULL, "
                f"created_at TEXT NOT NULL{_REVIEW_QUEUE_FK}{_PROJECT_FK})"
            )
        )
        assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
    engine.dispose()


@pytest.mark.parametrize("nullable_field", ["review_queue_item_id", "client_request_id"])
def test_revision_0041_rejects_nullable_event_request_identity_without_writes(
    nullable_field: str,
) -> None:
    """A UNIQUE key cannot protect reviewer request IDs when SQLite permits NULL."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO preserved VALUES ('original scientific observations')")
        )
        allowed = (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete'"
        )
        schema = _REVIEW_REQUEST_SCHEMA.replace(
            f"{nullable_field} TEXT NOT NULL", f"{nullable_field} TEXT"
        )
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({schema}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})), "
                "CONSTRAINT uq_review_queue_item_event_request "
                "UNIQUE (review_queue_item_id, client_request_id))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE review_queue_bulk_requests ("
                "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "project_id TEXT NOT NULL, action TEXT NOT NULL, "
                "actor TEXT NOT NULL, reason TEXT, item_ids_json TEXT NOT NULL, "
                f"created_at TEXT NOT NULL{_REVIEW_QUEUE_FK}{_PROJECT_FK})"
            )
        )
        with pytest.raises(RuntimeError, match="nullable review-event idempotency"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
        assert connection.scalar(text("SELECT value FROM preserved")) == (
            "original scientific observations"
        )
    engine.dispose()


@pytest.mark.parametrize(
    "unique_sql",
    [
        "",
        ", UNIQUE (review_queue_item_id, client_request_id)",
        ", CONSTRAINT renamed_request UNIQUE (review_queue_item_id, client_request_id)",
        ", CONSTRAINT uq_review_queue_item_event_request "
        "UNIQUE (review_queue_id, client_request_id)",
    ],
)
def test_revision_0041_rejects_unsafe_event_idempotency_without_writes(
    unique_sql: str,
) -> None:
    """A forged 0041 marker must not allow duplicate reviewer request IDs."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('original observations')"))
        allowed = (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete'"
        )
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})){unique_sql})"
            )
        )
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type) "
                "VALUES ('original-event', 'comment')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE review_queue_bulk_requests ("
                "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "project_id TEXT NOT NULL, action TEXT NOT NULL, "
                "actor TEXT NOT NULL, reason TEXT, item_ids_json TEXT NOT NULL, "
                f"created_at TEXT NOT NULL{_REVIEW_QUEUE_FK}{_PROJECT_FK})"
            )
        )
        with pytest.raises(RuntimeError, match="review-event idempotency"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
        assert connection.scalar(text("SELECT value FROM preserved")) == "original observations"
        assert (
            connection.scalar(text("SELECT id FROM review_queue_item_events")) == "original-event"
        )
    engine.dispose()


@pytest.mark.parametrize(
    "foreign_keys",
    [
        "",
        _REVIEW_QUEUE_FK,
        _PROJECT_FK,
        _REVIEW_QUEUE_FK.replace("RESTRICT", "CASCADE") + _PROJECT_FK,
        _REVIEW_QUEUE_FK + _PROJECT_FK.replace("projects(id)", "review_queues(id)"),
        _REVIEW_QUEUE_FK + _PROJECT_FK.replace("RESTRICT", "CASCADE"),
    ],
)
def test_revision_0041_rejects_missing_or_unsafe_bulk_foreign_keys(
    foreign_keys: str,
) -> None:
    """Reject orphanable or cascading QC request history without data writes."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('research evidence')"))
        allowed = (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete'"
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
                "CREATE TABLE review_queue_bulk_requests ("
                "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "project_id TEXT NOT NULL, action TEXT NOT NULL, "
                "actor TEXT NOT NULL, reason TEXT, item_ids_json TEXT NOT NULL, "
                f"created_at TEXT NOT NULL{foreign_keys})"
            )
        )
        with pytest.raises(RuntimeError, match="required RESTRICT links"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT value FROM preserved")) == "research evidence"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
        assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_bulk_requests")) == 0
    engine.dispose()


@pytest.mark.parametrize(
    "nullable_field",
    [
        "id",
        "review_queue_id",
        "project_id",
        "action",
        "actor",
        "item_ids_json",
        "created_at",
    ],
)
def test_revision_0041_rejects_nullable_bulk_identity_without_writes(
    nullable_field: str,
) -> None:
    """A forged registry cannot accept missing reviewer/scope/batch evidence."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0041')"))
        connection.execute(text("CREATE TABLE preserved (value TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO preserved VALUES ('original research data')"))
        allowed = (
            "'comment', 'assign', 'unassign', 'triage_start', "
            "'triage_skip', 'triage_return', 'triage_complete'"
        )
        connection.execute(
            text(
                f"CREATE TABLE review_queue_item_events ({REVIEW_SCHEMA}, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        required = [
            "id",
            "review_queue_id",
            "project_id",
            "action",
            "actor",
            "item_ids_json",
            "created_at",
        ]
        columns = [
            f"{field} TEXT"
            f"{'' if field == nullable_field else ' NOT NULL'}"
            f"{' PRIMARY KEY' if field == 'id' else ''}"
            for field in required
        ]
        columns.append("reason TEXT")
        connection.execute(text(f"CREATE TABLE review_queue_bulk_requests ({', '.join(columns)})"))

        with pytest.raises(RuntimeError, match="nullable required columns"):
            assert_compatible_revision_0038(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
        assert connection.scalar(text("SELECT value FROM preserved")) == "original research data"
        assert connection.scalar(text("SELECT COUNT(*) FROM review_queue_bulk_requests")) == 0
    engine.dispose()
