"""Desktop migration-lineage safety, including the already-at-head fast path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session


def _prepare_desktop_migration(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0038"),
    )
    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        lambda *_args, **_kwargs: pytest.fail("Already-at-head must not run upgrade"),
    )


def test_desktop_rejects_foreign_0038_even_when_at_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
        connection.execute(text("CREATE TABLE scientific_records (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO scientific_records VALUES ('preserve-me')"))
    _prepare_desktop_migration(monkeypatch, engine)

    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    with pytest.raises(RuntimeError, match="Unsafe ReefVision Alembic revision 0038"):
        desktop.run_pending_migrations(settings)

    # No schema changes or revision stamping are permitted on failure.
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
        assert connection.scalar(text("SELECT id FROM scientific_records")) == "preserve-me"


def test_desktop_accepts_native_0038_at_head_without_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
        connection.execute(
            text(
                "CREATE TABLE review_queue_item_events ("
                "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
                "project_id TEXT, client_request_id TEXT, event_type TEXT, actor TEXT, "
                "comment TEXT, assignee TEXT, created_at TEXT)"
            )
        )
    _prepare_desktop_migration(monkeypatch, engine)

    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    desktop.run_pending_migrations(settings)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"



def _prepare_fresh_desktop_migration(
    monkeypatch: pytest.MonkeyPatch,
    engine: object,
    *,
    upgrade: object,
) -> None:
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: "0038"),
    )
    monkeypatch.setattr(desktop.command, "upgrade", upgrade)


def test_desktop_rejects_missing_packaged_migration_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: None),
    )
    settings = SimpleNamespace(
        resolved_database_url=f"sqlite+pysqlite:///{tmp_path / 'untouched.sqlite'}"
    )
    with pytest.raises(RuntimeError, match="no packaged Alembic migration head"):
        desktop.run_pending_migrations(settings)
    assert not (tmp_path / "untouched.sqlite").exists()


def test_desktop_rejects_noop_migration_without_touching_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE preserved (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO preserved VALUES ('retain-me')"))
    _prepare_fresh_desktop_migration(monkeypatch, engine, upgrade=lambda *_args: None)

    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    with pytest.raises(RuntimeError, match="did not reach the expected Alembic"):
        desktop.run_pending_migrations(settings)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT id FROM preserved")) == "retain-me"
        assert not connection.dialect.has_table(connection, "alembic_version")


def test_desktop_verifies_successful_native_review_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")

    def apply_native_review_revision(*_args: object) -> None:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('0038')"))
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
                    "project_id TEXT, client_request_id TEXT, event_type TEXT, actor TEXT, "
                    "comment TEXT, assignee TEXT, created_at TEXT)"
                )
            )

    _prepare_fresh_desktop_migration(monkeypatch, engine, upgrade=apply_native_review_revision)
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    desktop.run_pending_migrations(settings)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
