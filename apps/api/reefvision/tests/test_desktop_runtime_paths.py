from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
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


def _add_native_review_table(
    database: Path, *, revision: str | None = None, nullable_event_type: bool = False
) -> None:
    """Make a synthetic revision stamp satisfy the 1.6 lineage guard.

    The separate real-migration regression exercises actual Alembic DDL.
    """
    with sqlite3.connect(database) as connection:
        stamped_revision = revision
        if stamped_revision is None:
            stamped_revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        allowed_events = (
            "'comment', 'assign', 'unassign', 'triage_start', 'triage_skip', 'triage_return'"
        )
        if stamped_revision in {"0040", "0041"}:
            allowed_events += ", 'triage_complete'"
        event_type_check = (
            f", CONSTRAINT ck_review_queue_item_event_type CHECK (event_type IN ({allowed_events}))"
            if stamped_revision in {"0039", "0040", "0041"}
            else ""
        )
        event_type_decl = "event_type TEXT" if nullable_event_type else "event_type TEXT NOT NULL"
        connection.execute(
            "CREATE TABLE review_queue_item_events ("
            "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
            "project_id TEXT, client_request_id TEXT, "
            f"{event_type_decl}, actor TEXT, "
            f"comment TEXT, assignee TEXT, created_at TEXT{event_type_check})"
        )
        if stamped_revision == "0041":
            # Synthetic schema identity must include the real 0041 registry
            # contract, not just the 0040 review-event table.
            connection.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
            connection.execute("CREATE TABLE review_queues (id TEXT PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE review_queue_bulk_requests ("
                "id TEXT PRIMARY KEY NOT NULL, "
                "review_queue_id TEXT NOT NULL REFERENCES review_queues(id) ON DELETE RESTRICT, "
                "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT, "
                "action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT, "
                "item_ids_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
        if revision is not None:
            connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()


def test_provider_runtime_dir_uses_desktop_data_dir_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "desktop-data"
    working_dir = tmp_path / "program-files-like-cwd"
    working_dir.mkdir()

    monkeypatch.chdir(working_dir)
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(data_dir))

    assert provider_runtime_dir() == data_dir.resolve() / "provider-runtime"


def test_provider_runtime_explicit_inputs_override_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch: pytest.MonkeyPatch,
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
    # A bare 0038-0040 stamp is not a valid review-events database.
    # The desktop must validate schema identity even on its fast path.
    if current_head in {"0038", "0039", "0040", "0041"}:
        _add_native_review_table(database)
    before = database.read_bytes()

    def unexpected_upgrade(*args, **kwargs) -> None:
        raise AssertionError("Alembic upgrade must not run when the database is already at head")

    monkeypatch.setattr(
        command,
        "upgrade",
        unexpected_upgrade,
    )

    desktop.run_pending_migrations(settings)

    assert database.read_bytes() == before


def test_older_database_revision_still_invokes_alembic_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _desktop_settings(tmp_path / "older")
    _stamp_database(settings, "0034")

    alembic_ini, migrations_dir = desktop.resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(migrations_dir))
    current_head = ScriptDirectory.from_config(config).get_current_head()
    assert current_head is not None

    calls: list[str] = []

    def record_upgrade(config, target: str) -> None:
        assert config.get_main_option("sqlalchemy.url") == settings.resolved_database_url
        calls.append(target)
        # The desktop now checks the post-upgrade revision and lineage.
        # Model a successful migration rather than a no-op mock.
        _add_native_review_table(settings.resolved_data_dir / "reefvision.db", revision=current_head)

    monkeypatch.setattr(
        command,
        "upgrade",
        record_upgrade,
    )

    desktop.run_pending_migrations(settings)

    assert calls == ["head"]


def test_current_0040_stamp_with_0039_event_check_fails_closed(
    tmp_path: Path,
) -> None:
    """A stale audit CHECK must not pass desktop startup at revision 0040."""
    settings = _desktop_settings(tmp_path / "stale-check")
    database = _stamp_database(settings, "0039")
    _add_native_review_table(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = '0040'")
        connection.commit()

    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="CHECK constraint still excludes"):
        desktop.run_pending_migrations(settings)
    assert database.read_bytes() == before


def test_current_0040_stamp_with_nullable_event_type_fails_closed(
    tmp_path: Path,
) -> None:
    """A CHECK allowlist cannot protect SQLite audit rows with NULL event types."""
    settings = _desktop_settings(tmp_path / "nullable-event")
    database = _stamp_database(settings, "0040")
    _add_native_review_table(database, nullable_event_type=True)
    before = database.read_bytes()

    with pytest.raises(RuntimeError, match="event_type is nullable"):
        desktop.run_pending_migrations(settings)

    assert database.read_bytes() == before


def test_0041_stamp_without_bulk_registry_fails_closed_without_mutation(
    tmp_path: Path,
) -> None:
    """A bare 0041 stamp cannot bypass its required QC request registry."""
    settings = _desktop_settings(tmp_path / "missing-registry")
    database = _stamp_database(settings, "0040")
    _add_native_review_table(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = '0041'")
        connection.commit()

    before = database.read_bytes()
    with pytest.raises(RuntimeError, match="bulk request registry"):
        desktop.run_pending_migrations(settings)
    assert database.read_bytes() == before
