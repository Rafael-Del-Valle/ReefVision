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
    (None,),
    ("",),
    ("   ",),
]


def _seed_database(engine: object, stamps: tuple[str | None, ...]) -> None:
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
    tmp_path: Path, stamps: tuple[str | None, ...]
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


@pytest.mark.parametrize("stamps", [("0037", "0037"), ("0036", "0037"), (None,)])
def test_desktop_refuses_ambiguous_stamps_before_alembic_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stamps: tuple[str | None, ...],
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
