"""Fail closed on a lone foreign Alembic stamp before desktop startup.

An incomplete 1.1 restore can retain revision 0042 but lose every known
scientific table. That does not turn it into a valid pre-review 1.6 database.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


def _seed(engine: object, revision: str, *, populated: bool) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        if populated:
            connection.execute(
                text("CREATE TABLE observations (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO observations VALUES ('coral-1', 'preserve this record')")
            )


def _evidence(connection: object, *, populated: bool) -> tuple[object, ...]:
    return (
        tuple(
            connection.execute(
                text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
            ).all()
        ),
        tuple(connection.execute(text("SELECT version_num FROM alembic_version")).all()),
        tuple(connection.execute(text("SELECT id, value FROM observations")).all())
        if populated
        else None,
    )


@pytest.mark.parametrize(
    "revision",
    ["0000", "0042", "0043", "foreign_head", "0037 ", "53ba400993dc"],
)
@pytest.mark.parametrize("populated", [False, True])
def test_unknown_single_revision_preserves_science_and_schema(
    tmp_path: Path, revision: str, populated: bool
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'foreign-stamp.sqlite'}")
    _seed(engine, revision, populated=populated)
    with engine.connect() as connection:
        original = _evidence(connection, populated=populated)
    for _ in range(2):
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="unsupported or foreign revision"):
                assert_compatible_revision_0038(connection)
            assert _evidence(connection, populated=populated) == original
    engine.dispose()


@pytest.mark.parametrize("revision", ["0001", "0014", "53ba400993db", "0015", "0037"])
def test_packaged_legacy_pre_review_stamps_still_pass_read_only(
    tmp_path: Path, revision: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'legacy-stamp.sqlite'}")
    _seed(engine, revision, populated=False)
    with engine.connect() as connection:
        before = _evidence(connection, populated=False)
        assert_compatible_revision_0038(connection)
        assert _evidence(connection, populated=False) == before
    engine.dispose()


@pytest.mark.parametrize("revision", ["0042", "foreign_head", "0037 "])
def test_desktop_never_invokes_alembic_on_unknown_single_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'desktop-foreign.sqlite'}")
    _seed(engine, revision, populated=True)
    with engine.connect() as connection:
        before = _evidence(connection, populated=True)
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
            "An unknown single stamp must not reach a schema-changing upgrade"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="unsupported or foreign revision"):
            desktop.run_pending_migrations(settings)
        with engine.connect() as connection:
            assert _evidence(connection, populated=True) == before
    engine.dispose()
