"""Nonmutating desktop --skip-migrations safety for ReefVision 1.6."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reefvision import desktop
from reefvision.config import Settings


def _desktop_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="desktop",
        data_dir=tmp_path / "science-data",
        database_url=f"sqlite:///{(tmp_path / 'science-data' / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
    )


def test_skip_migrations_missing_file_fails_before_data_directory_or_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _desktop_settings(tmp_path)
    monkeypatch.setattr(desktop, "build_settings", lambda _options: settings)

    async def never_start(*_args: object) -> None:
        pytest.fail("A missing schema must never reach API startup")

    monkeypatch.setattr(desktop, "run_api_server", never_start)
    assert desktop.main(["--skip-migrations", "--data-dir", str(settings.data_dir)]) == 1
    assert not settings.data_dir.exists()


@pytest.mark.parametrize(
    ("revision", "foreign_science", "error"),
    [
        ("0037", False, "outdated or unknown"),
        ("0038", True, "Unsafe ReefVision"),
    ],
)
def test_skip_migrations_rejects_stale_or_foreign_science_without_writing(
    tmp_path: Path, revision: str, foreign_science: bool, error: str
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    database_path = settings.resolved_data_dir / "reefvision.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        connection.execute("CREATE TABLE preserved_observations (note TEXT NOT NULL)")
        connection.execute("INSERT INTO preserved_observations VALUES ('original biological note')")
        if foreign_science:
            connection.execute("CREATE TABLE scientific_records (id TEXT PRIMARY KEY)")
            connection.execute("INSERT INTO scientific_records VALUES ('science-keep')")
    original_bytes = database_path.read_bytes()

    with pytest.raises(RuntimeError, match=error):
        desktop.require_existing_desktop_schema(settings)

    assert database_path.read_bytes() == original_bytes
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            revision,
        )
        assert connection.execute("SELECT note FROM preserved_observations").fetchone() == (
            "original biological note",
        )
        if foreign_science:
            assert connection.execute("SELECT id FROM scientific_records").fetchone() == (
                "science-keep",
            )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://researcher@unreachable.invalid/reefvision",
        "mysql://researcher@unreachable.invalid/reefvision",
    ],
)
def test_skip_migrations_refuses_external_database_before_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    from reefvision.db import session

    settings = Settings(
        env="desktop",
        data_dir=tmp_path / "science-data",
        database_url=database_url,
        background_worker_enabled=False,
    )
    monkeypatch.setattr(
        session,
        "create_database_engine",
        lambda _settings: pytest.fail("Offline startup must not open an external database"),
    )

    with pytest.raises(RuntimeError, match="external database backends are unsupported"):
        desktop.require_existing_desktop_schema(settings)

    assert not settings.data_dir.exists()


def test_skip_migrations_rejects_corrupt_sqlite_without_creating_replacement(
    tmp_path: Path,
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    database_path = settings.resolved_data_dir / "reefvision.db"
    damaged_bytes = b"not-a-sqlite-database\x00preserve-for-scientific-recovery"
    database_path.write_bytes(damaged_bytes)

    with pytest.raises(RuntimeError, match="could not inspect the existing SQLite"):
        desktop.require_existing_desktop_schema(settings)

    assert database_path.read_bytes() == damaged_bytes


def test_skip_migrations_rejects_orphaned_references_at_valid_head_without_repair(
    tmp_path: Path,
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    desktop.run_pending_migrations(settings)
    database_path = settings.resolved_data_dir / "reefvision.db"

    # Simulate an interrupted external restore which retained a valid 0041
    # stamp but not the biological parent evidence. SQLite permits this when
    # a separate writer had foreign-key enforcement disabled.
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE preserved_parent (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE preserved_child (id INTEGER PRIMARY KEY, "
            "parent_id INTEGER NOT NULL REFERENCES preserved_parent(id))"
        )
        connection.execute("INSERT INTO preserved_child VALUES (1, 73)")
        connection.execute("CREATE TABLE biological_notes (note TEXT NOT NULL)")
        connection.execute("INSERT INTO biological_notes VALUES ('keep original evidence')")
    original_bytes = database_path.read_bytes()

    with pytest.raises(RuntimeError, match="orphaned scientific or reviewer references"):
        desktop.require_existing_desktop_schema(settings)

    assert database_path.read_bytes() == original_bytes
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0041",
        )
        assert connection.execute("SELECT parent_id FROM preserved_child").fetchone() == (73,)
        assert connection.execute("SELECT note FROM biological_notes").fetchone() == (
            "keep original evidence",
        )


def test_skip_migrations_allows_actual_packaged_head_without_upgrading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    desktop.run_pending_migrations(settings)
    database_path = settings.resolved_data_dir / "reefvision.db"

    def never_upgrade(*_args: object, **_kwargs: object) -> None:
        pytest.fail("--skip-migrations must never invoke Alembic upgrade")

    monkeypatch.setattr(desktop.command, "upgrade", never_upgrade)
    desktop.require_existing_desktop_schema(settings)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0041",)
