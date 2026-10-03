from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from reefvision import desktop
from reefvision.config import Settings
from reefvision.ml.dependencies import provider_runtime_dir


def _desktop_settings(data_dir: Path) -> Settings:
    return Settings(
        env="desktop",
        data_dir=data_dir,
        safe_mode=True,
        background_worker_enabled=False,
    )


def _stamp_database(settings: Settings, revision: str) -> Path:
    settings.ensure_directories()
    database = settings.resolved_data_dir / "reefvision.db"

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
        connection.commit()

    return database


def test_provider_runtime_dir_uses_desktop_data_dir_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "desktop-data"
    working_dir = tmp_path / "program-files-like-cwd"
    working_dir.mkdir()

    monkeypatch.chdir(working_dir)
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(data_dir))

    assert provider_runtime_dir() == data_dir.resolve() / "provider-runtime"


def test_provider_runtime_explicit_inputs_override_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    environment_dir = tmp_path / "environment"
    settings_dir = tmp_path / "settings"
    explicit_dir = tmp_path / "explicit"

    monkeypatch.setenv("REEFVISION_DATA_DIR", str(environment_dir))

    settings = _desktop_settings(settings_dir)

    assert provider_runtime_dir(settings) == (settings_dir.resolve() / "provider-runtime")

    assert provider_runtime_dir(data_dir=explicit_dir) == (explicit_dir / "provider-runtime")


def test_current_database_revision_skips_alembic_upgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _desktop_settings(tmp_path / "current")

    alembic_ini, migrations_dir = desktop.resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.set_main_option(
        "script_location",
        str(migrations_dir),
    )
    current_head = ScriptDirectory.from_config(config).get_current_head()

    assert current_head is not None

    database = _stamp_database(
        settings,
        current_head,
    )
    before = database.read_bytes()

    def unexpected_upgrade(*args, **kwargs) -> None:
        raise AssertionError("Alembic upgrade must not run when the database is already at head")

    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        unexpected_upgrade,
    )

    desktop.run_pending_migrations(settings)

    assert database.read_bytes() == before


def test_older_database_revision_still_invokes_alembic_upgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _desktop_settings(tmp_path / "older")
    _stamp_database(settings, "0034")

    calls: list[str] = []

    def record_upgrade(config, target: str) -> None:
        assert config.get_main_option("sqlalchemy.url") == (settings.resolved_database_url)
        calls.append(target)

    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        record_upgrade,
    )

    desktop.run_pending_migrations(settings)

    assert calls == ["head"]
