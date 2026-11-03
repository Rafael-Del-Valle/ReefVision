"""Reject ambiguous Alembic pre-review stamps without touching biological data.

The 1.6 desktop preflight must inspect even a 0037/unknown/empty version
table before Alembic can upgrade it. SQLite databases restored from damaged
or interrupted backups can retain multiple or malformed revision rows.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


_BAD_STAMPS = [
    ("0037", "0037"),
    ("0036", "0037"),
    ("0037", "foreign_head"),
    ("0037", None),  # A mixed valid/NULL stamp must not bypass validation.
    ("0037", ""),  # An empty concurrent head is also ambiguous.
    ("0037", b"0037"),  # SQLite preserves BLOB stamps despite TEXT affinity.
    (None,),
    ("",),
    ("   ",),
    (),  # An empty revision table with existing research tables is unsafe.
]


def _seed_database(engine: object, stamps: tuple[str | bytes | None, ...]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE observations (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO observations VALUES ('coral-1', 'original research record')")
        )
        # Deliberately emulate a damaged/partially restored Alembic table.
        # The real Alembic PK/NOT NULL constraints would normally prevent
        # duplicates and NULL stamps; the desktop must still refuse them.
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        for stamp in stamps:
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:stamp)"),
                {"stamp": stamp},
            )


def _snapshot(connection: object) -> tuple[object, ...]:
    return (
        tuple(
            connection.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
            ).all()
        ),
        tuple(connection.execute(text("SELECT id, value FROM observations")).all()),
        tuple(connection.execute(text("SELECT version_num FROM alembic_version")).all()),
    )


@pytest.mark.parametrize("stamps", _BAD_STAMPS)
def test_pre_review_ambiguous_stamps_fail_closed_without_rewriting_science(
    tmp_path: Path, stamps: tuple[str | bytes | None, ...]
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ambiguous.sqlite'}")
    _seed_database(engine, stamps)
    with engine.connect() as connection:
        before = _snapshot(connection)
    for _ in range(2):
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="Unsafe ReefVision Alembic"):
                assert_compatible_revision_0038(connection)
            assert _snapshot(connection) == before
    engine.dispose()


@pytest.mark.parametrize(
    "stamps", [("0037", "0037"), ("0036", "0037"), ("0037", None), ("0037", b"0037"), (None,), ()]
)
def test_desktop_refuses_ambiguous_stamps_before_alembic_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stamps: tuple[str | bytes | None, ...],
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'desktop-ambiguous.sqlite'}")
    _seed_database(engine, stamps)
    with engine.connect() as connection:
        before = _snapshot(connection)
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
            "Ambiguous Alembic stamps must never reach a schema-changing upgrade"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Unsafe ReefVision Alembic"):
            desktop.run_pending_migrations(settings)
        with engine.connect() as connection:
            assert _snapshot(connection) == before
    engine.dispose()


def test_single_pre_review_stamp_remains_compatible(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'valid.sqlite'}")
    _seed_database(engine, ("0037",))
    with engine.connect() as connection:
        before = _snapshot(connection)
        assert_compatible_revision_0038(connection)
        assert _snapshot(connection) == before
    engine.dispose()


def test_empty_revision_table_on_empty_database_remains_compatible(tmp_path: Path) -> None:
    """A genuinely new database with an empty Alembic table may initialize."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'empty.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        before = tuple(
            connection.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
            ).all()
        )
        assert_compatible_revision_0038(connection)
        assert tuple(
            connection.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
            ).all()
        ) == before
    engine.dispose()


@pytest.mark.parametrize(
    "table_name",
    ["observations", "projects", "review_queues", "workflow_runs", "legacy_table"],
)
def test_unversioned_populated_database_preserves_all_existing_data(
    tmp_path: Path, table_name: str
) -> None:
    """A missing Alembic table never licenses replay of initial migrations."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'unversioned.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(f"CREATE TABLE {table_name} (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        )
        connection.execute(
            text(f"INSERT INTO {table_name} VALUES ('coral-1', 'preserved research')")
        )

    def snapshot() -> tuple[object, ...]:
        with engine.connect() as connection:
            return (
                tuple(
                    connection.execute(
                        text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
                    ).all()
                ),
                tuple(connection.execute(text(f"SELECT id, value FROM {table_name}")).all()),
            )

    before = snapshot()
    for _ in range(2):
        with engine.connect() as connection, pytest.raises(
            RuntimeError, match="unversioned populated database"
        ):
            assert_compatible_revision_0038(connection)
        assert snapshot() == before
    engine.dispose()


@pytest.mark.parametrize("table_name", ["observations", "projects", "workflow_runs"])
def test_desktop_refuses_unversioned_populated_database_before_upgrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, table_name: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'desktop-unversioned.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(f"CREATE TABLE {table_name} (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        )
        connection.execute(
            text(f"INSERT INTO {table_name} VALUES ('coral-1', 'original record')")
        )
    with engine.connect() as connection:
        before = (
            tuple(
                connection.execute(
                    text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
                ).all()
            ),
            tuple(connection.execute(text(f"SELECT id, value FROM {table_name}")).all()),
        )
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
            "A populated database without Alembic provenance must never be upgraded"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="unversioned populated database"):
            desktop.run_pending_migrations(settings)
        with engine.connect() as connection:
            assert (
                tuple(
                    connection.execute(
                        text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
                    ).all()
                ),
                tuple(connection.execute(text(f"SELECT id, value FROM {table_name}")).all()),
            ) == before
    engine.dispose()


def test_genuinely_empty_unversioned_database_remains_compatible(tmp_path: Path) -> None:
    """Fresh databases without any tables must still initialize normally."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'fresh.sqlite'}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all() == []
        assert_compatible_revision_0038(connection)
        assert connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all() == []
    engine.dispose()


@pytest.mark.parametrize("with_version_table", [False, True])
def test_orphaned_research_view_blocks_migration_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    with_version_table: bool,
) -> None:
    """A preserved view alone is not a fresh database after table loss."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'orphan-view.sqlite'}")
    with engine.begin() as connection:
        if with_version_table:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        # SQLite permits views referencing tables that no longer exist.
        connection.execute(
            text("CREATE VIEW coral_observations AS SELECT id FROM missing_observations")
        )

    def snapshot() -> tuple[object, ...]:
        with engine.connect() as connection:
            return tuple(
                connection.execute(
                    text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
                ).all()
            )

    before = snapshot()
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
            "Preserved research views must not reach Alembic upgrade"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with engine.connect() as connection, pytest.raises(
            RuntimeError, match="Unsafe ReefVision"
        ):
            assert_compatible_revision_0038(connection)
        with pytest.raises(RuntimeError, match="Unsafe ReefVision"):
            desktop.run_pending_migrations(settings)
        assert snapshot() == before
    engine.dispose()


@pytest.mark.parametrize("revision", ["0037", "0036"])
def test_pre_review_stamp_with_orphaned_view_refuses_upgrade_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, revision: str
) -> None:
    """A plausible old stamp cannot license overwriting a restored research view."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'old-view.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(
            text("CREATE VIEW coral_observations AS SELECT id FROM missing_observations")
        )

    def snapshot() -> tuple[object, ...]:
        with engine.connect() as connection:
            return tuple(
                connection.execute(
                    text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
                ).all()
            )

    before = snapshot()
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0041"),
    )
    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        lambda *_args, **_kwargs: pytest.fail("Orphaned views must not reach Alembic"),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with engine.connect() as connection, pytest.raises(
            RuntimeError, match="pre-review schema with preserved views"
        ):
            assert_compatible_revision_0038(connection)
        with pytest.raises(RuntimeError, match="pre-review schema with preserved views"):
            desktop.run_pending_migrations(settings)
        assert snapshot() == before
    engine.dispose()
