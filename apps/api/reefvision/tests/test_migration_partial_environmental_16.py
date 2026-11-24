"""Preserve 1.1 environmental-event and analysis evidence on 1.6 upgrades.

Version 1.1 added a standalone event-definition table in 0040 and two
independent environmental-analysis tables in 0042. SQLite DDL can survive an
interrupted migration or partial restore without the earlier 0038 tables.
Neither a plausible Alembic stamp nor unrelated 1.6 QC DDL authorizes writes.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038

SCIENTIFIC_EXTENSIONS = (
    "environmental_event_definitions",
    "environmental_analysis_definitions",
    "environmental_analysis_results",
)


def _partial_science(engine: object, revision: str | None, table: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE biological_observations (id TEXT, note TEXT)"))
        connection.execute(
            text("INSERT INTO biological_observations VALUES ('coral-1', 'preserve tissue')")
        )
        if revision is not None:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
        # The other scientific tables are intentionally absent to model a
        # failed 0040/0042 DDL step, not a complete 1.1 migration.
        connection.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
        connection.execute(text(f"INSERT INTO {table} VALUES ('scientific-record')"))


def _evidence(connection: object, table: str) -> tuple[object, ...]:
    return (
        tuple(
            connection.execute(
                text("SELECT name, sql FROM sqlite_master ORDER BY type, name")
            ).all()
        ),
        tuple(connection.execute(text("SELECT * FROM biological_observations")).all()),
        tuple(connection.execute(text(f"SELECT * FROM {table}")).all()),
        tuple(connection.execute(text("SELECT version_num FROM alembic_version")).all())
        if connection.dialect.has_table(connection, "alembic_version")
        else None,
    )


@pytest.mark.parametrize("table", SCIENTIFIC_EXTENSIONS)
@pytest.mark.parametrize("revision", [None, "0037", "0038", "0039", "0040", "0041", "0042"])
def test_partial_late_environmental_lineage_is_rejected_read_only(
    tmp_path: Path, revision: str | None, table: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'late-science.sqlite'}")
    _partial_science(engine, revision, table)
    with engine.connect() as connection:
        original = _evidence(connection, table)
    for _ in range(2):
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match=r"scientific|collision"):
                assert_compatible_revision_0038(connection)
            assert _evidence(connection, table) == original
    engine.dispose()


@pytest.mark.parametrize("table", SCIENTIFIC_EXTENSIONS)
@pytest.mark.parametrize("revision", [None, "0037"])
def test_desktop_migration_never_starts_on_partial_late_science(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revision: str | None,
    table: str,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'desktop-science.sqlite'}")
    _partial_science(engine, revision, table)
    with engine.connect() as connection:
        before = _evidence(connection, table)
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0041"),
    )
    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        lambda *_args, **_kwargs: pytest.fail(
            "A partially restored scientific schema must never run Alembic upgrade"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    with pytest.raises(RuntimeError, match="scientific"):
        desktop.run_pending_migrations(settings)
    with engine.connect() as connection:
        assert _evidence(connection, table) == before
    engine.dispose()


@pytest.mark.parametrize(
    "table",
    [
        "scientific_records",
        "environmental_cache_entries",
        "computed_metric_definitions",
        "computed_metric_results",
        "environmental_event_definitions",
        "environmental_analysis_definitions",
        "environmental_analysis_results",
        "review_queue_item_events",
        "review_queue_bulk_requests",
    ],
)
@pytest.mark.parametrize("kind", ["table", "view"])
def test_desktop_refuses_reserved_schema_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table: str, kind: str
) -> None:
    """Case-variant tables and reserved views cannot bypass startup preflight."""
    database = tmp_path / "reserved-schema.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0037')"))
        connection.execute(text("CREATE TABLE biological_observations (note TEXT)"))
        connection.execute(text("INSERT INTO biological_observations VALUES ('preserve tissue')"))
        if kind == "table":
            connection.execute(text(f'CREATE TABLE "{table.upper()}" (id TEXT PRIMARY KEY)'))
            connection.execute(
                text(f'INSERT INTO "{table.upper()}" VALUES (:record)'),
                {"record": "scientific-record"},
            )
        else:
            connection.execute(
                text(f'CREATE VIEW "{table}" AS SELECT note FROM biological_observations')
            )
        # SQLite resolves the uppercase table via its lowercase migration name.
        assert connection.execute(text(f'SELECT * FROM "{table}"')).fetchone() is not None
    original = database.read_bytes()
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0041"),
    )
    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        lambda *_args, **_kwargs: pytest.fail("Reserved schema aliases must block Alembic"),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with (
            engine.connect() as connection,
            pytest.raises(RuntimeError, match="noncanonical reserved schema object"),
        ):
            assert_compatible_revision_0038(connection)
        with pytest.raises(RuntimeError, match="noncanonical reserved schema object"):
            desktop.run_pending_migrations(settings)
        assert database.read_bytes() == original
    engine.dispose()


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("ALEMBIC_VERSION", "table"),
        ("Alembic_Version", "table"),
        ("alembic_version", "view"),
        ("ALEMBIC_VERSION", "view"),
    ],
)
def test_desktop_refuses_noncanonical_revision_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, kind: str
) -> None:
    database = tmp_path / "revision-object.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE biological_observations (version_num TEXT)")
        connection.exec_driver_sql("INSERT INTO biological_observations VALUES ('0037')")
        if kind == "table":
            connection.exec_driver_sql(
                f'CREATE TABLE "{name}" (version_num TEXT NOT NULL PRIMARY KEY)'
            )
            connection.exec_driver_sql(f'INSERT INTO "{name}" VALUES (?)', ("0037",))
        else:
            connection.exec_driver_sql(
                f'CREATE VIEW "{name}" AS SELECT version_num FROM biological_observations'
            )
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0037"
    original = database.read_bytes()
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0041"),
    )
    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        lambda *_args, **_kwargs: pytest.fail("Noncanonical revision object must block upgrade"),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="noncanonical reserved schema object"):
            desktop.run_pending_migrations(settings)
        assert database.read_bytes() == original
    engine.dispose()
