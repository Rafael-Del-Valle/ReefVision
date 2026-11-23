"""Nonmutating desktop --skip-migrations safety for ReefVision 1.6."""

from __future__ import annotations

import os
import shutil
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


def test_skip_migrations_rejects_unique_index_corruption_without_repair(
    tmp_path: Path,
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    desktop.run_pending_migrations(settings)
    database_path = settings.resolved_data_dir / "reefvision.db"

    # Simulate an externally damaged index schema: the existing index has
    # duplicate biological observations but its schema claims UNIQUE.
    # SQLite quick_check can report "ok" for this inconsistency.
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE restored_observations "
            "(id INTEGER PRIMARY KEY, identification TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO restored_observations (identification) VALUES (?)",
            [("Swiftia open",), ("Swiftia open",)],
        )
        connection.execute(
            "CREATE INDEX restored_identification_idx ON restored_observations(identification)"
        )
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_schema SET sql = "
            "REPLACE(sql, 'CREATE INDEX', 'CREATE UNIQUE INDEX') "
            "WHERE name = 'restored_identification_idx'"
        )
        connection.execute("PRAGMA writable_schema=OFF")

    original_bytes = database_path.read_bytes()
    with sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True) as probe:
        assert probe.execute("PRAGMA quick_check(1)").fetchone() == ("ok",)
        assert probe.execute("PRAGMA integrity_check(1)").fetchone() != ("ok",)

    with pytest.raises(RuntimeError, match="damaged SQLite database"):
        desktop.require_existing_desktop_schema(settings)

    assert database_path.read_bytes() == original_bytes
    with sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True) as probe:
        assert probe.execute("SELECT version_num FROM alembic_version").fetchone() == ("0041",)
        assert probe.execute("SELECT COUNT(*) FROM restored_observations").fetchone() == (2,)


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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0041",)
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


def test_skip_migrations_rejects_replaced_valid_database_between_preflights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    desktop.run_pending_migrations(settings)
    database_path = settings.resolved_data_dir / "reefvision.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE biological_notes (note TEXT NOT NULL)")
        connection.execute("INSERT INTO biological_notes VALUES ('original Swiftia note')")
    original_bytes = database_path.read_bytes()
    original_backup = tmp_path / "original-scientific-database.sqlite"
    original_backup.write_bytes(original_bytes)

    # Both files are real, intact 0041 databases. A revision stamp check
    # alone cannot tell that the integrity audit and lineage audit inspected
    # two different observations after a restore or symlink replacement.
    replacement = tmp_path / "replacement-scientific-database.sqlite"
    shutil.copy2(database_path, replacement)
    with sqlite3.connect(replacement) as connection:
        connection.execute("UPDATE biological_notes SET note = 'different Swiftia note'")
    real_resolve = desktop.resolve_alembic_paths

    def replace_between_preflights(resource_root: Path | None = None) -> tuple[Path, Path]:
        os.replace(replacement, database_path)
        return real_resolve(resource_root)

    monkeypatch.setattr(desktop, "resolve_alembic_paths", replace_between_preflights)
    from reefvision.db import session

    monkeypatch.setattr(
        session,
        "create_database_engine",
        lambda _settings: pytest.fail("A substituted database must not reach a writable engine"),
    )

    with pytest.raises(RuntimeError, match="database file changed during validation"):
        desktop.require_existing_desktop_schema(settings)

    # Preflight never silently rewrites either scientific record. The
    # researcher-controlled test substitution leaves the original backup.
    assert original_backup.read_bytes() == original_bytes
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0041",)
        assert connection.execute("SELECT note FROM biological_notes").fetchone() == (
            "different Swiftia note",
        )
    with sqlite3.connect(original_backup) as connection:
        assert connection.execute("SELECT note FROM biological_notes").fetchone() == (
            "original Swiftia note",
        )


@pytest.mark.parametrize("preexisting_wal", [False, True])
def test_skip_migrations_refuses_wal_only_changes_between_preflights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preexisting_wal: bool
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    desktop.run_pending_migrations(settings)
    database_path = settings.resolved_data_dir / "reefvision.db"
    with sqlite3.connect(database_path) as setup:
        setup.execute("CREATE TABLE biological_notes (note TEXT NOT NULL)")
        setup.execute("INSERT INTO biological_notes VALUES ('original Swiftia note')")
        setup.commit()
        assert setup.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)

    # Keep a separate writer open so committed frames stay in the WAL rather
    # than being checkpointed into the main database. SQLite's main-file stat
    # therefore cannot establish that the reviewed observations were stable.
    writer = sqlite3.connect(database_path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    if preexisting_wal:
        writer.execute("INSERT INTO biological_notes VALUES ('prior reviewed note')")
        writer.commit()
    initial_database_stat = database_path.stat()
    wal_path = Path(f"{database_path}-wal")
    initial_wal_state = desktop._sqlite_wal_identity(wal_path)
    real_resolve = desktop.resolve_alembic_paths
    changed_during_preflight = False

    def change_wal_after_integrity(resource_root: Path | None = None) -> tuple[Path, Path]:
        nonlocal changed_during_preflight
        changed_during_preflight = True
        writer.execute("INSERT INTO biological_notes VALUES ('later biological note')")
        writer.commit()
        current_database_stat = database_path.stat()
        assert (
            current_database_stat.st_dev,
            current_database_stat.st_ino,
            current_database_stat.st_size,
            current_database_stat.st_mtime_ns,
        ) == (
            initial_database_stat.st_dev,
            initial_database_stat.st_ino,
            initial_database_stat.st_size,
            initial_database_stat.st_mtime_ns,
        )
        assert desktop._sqlite_wal_identity(wal_path) != initial_wal_state
        return real_resolve(resource_root)

    monkeypatch.setattr(desktop, "resolve_alembic_paths", change_wal_after_integrity)
    from reefvision.db import session

    monkeypatch.setattr(
        session,
        "create_database_engine",
        lambda _settings: pytest.fail("Changed WAL must not reach the write-capable engine"),
    )
    try:
        with pytest.raises(RuntimeError, match="SQLite WAL changed during validation"):
            desktop.require_existing_desktop_schema(settings)
        assert changed_during_preflight
        assert writer.execute("SELECT note FROM biological_notes ORDER BY rowid").fetchall() == (
            [
                ("original Swiftia note",),
                *([("prior reviewed note",)] if preexisting_wal else []),
                ("later biological note",),
            ]
        )
    finally:
        writer.close()


def test_skip_migrations_accepts_stable_nonempty_wal_without_upgrading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _desktop_settings(tmp_path)
    settings.ensure_directories()
    desktop.run_pending_migrations(settings)
    database_path = settings.resolved_data_dir / "reefvision.db"
    with sqlite3.connect(database_path) as setup:
        setup.execute("CREATE TABLE biological_notes (note TEXT NOT NULL)")
        setup.commit()
        assert setup.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)

    writer = sqlite3.connect(database_path)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO biological_notes VALUES ('reviewed Swiftia record')")
    writer.commit()
    wal_path = Path(f"{database_path}-wal")
    wal_before = desktop._sqlite_wal_identity(wal_path)
    assert wal_before is not None

    def never_upgrade(*_args: object, **_kwargs: object) -> None:
        pytest.fail("An unchanged WAL must not force a migration or stamp")

    monkeypatch.setattr(desktop.command, "upgrade", never_upgrade)
    try:
        desktop.require_existing_desktop_schema(settings)
        assert desktop._sqlite_wal_identity(wal_path) == wal_before
        assert writer.execute("SELECT note FROM biological_notes").fetchall() == [
            ("reviewed Swiftia record",)
        ]
    finally:
        writer.close()
