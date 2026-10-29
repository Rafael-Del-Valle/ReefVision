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
        # Revision 0041 requires the same named idempotency constraint as the
        # real audit migration. A bare synthetic stamp must not bypass it.
        request_identity = (
            ", CONSTRAINT uq_review_queue_item_event_request "
            "UNIQUE (review_queue_item_id, client_request_id)"
            if stamped_revision == "0041"
            else ""
        )
        request_item_decl = (
            "review_queue_item_id TEXT NOT NULL"
            if stamped_revision == "0041"
            else "review_queue_item_id TEXT"
        )
        request_key_decl = (
            "client_request_id TEXT NOT NULL"
            if stamped_revision == "0041"
            else "client_request_id TEXT"
        )
        # A stamped 0041 fixture must retain the actual 0038 NOT NULL
        # attribution contract; otherwise the desktop guard correctly refuses
        # it before exercising the intended startup/upgrade behavior.
        attribution_required = " NOT NULL" if stamped_revision == "0041" else ""
        connection.execute(
            "CREATE TABLE review_queue_item_events ("
            f"id TEXT PRIMARY KEY{attribution_required}, "
            f"review_queue_id TEXT{attribution_required}, {request_item_decl}, "
            f"project_id TEXT{attribution_required}, {request_key_decl}, "
            f"{event_type_decl}, actor TEXT{attribution_required}, "
            f"comment TEXT, assignee TEXT, "
            f"created_at TEXT{attribution_required}{event_type_check}{request_identity})"
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


def test_synthetic_0041_review_fixture_preserves_per_item_request_idempotency(
    tmp_path: Path,
) -> None:
    """The desktop startup fixture must model the real 0041 audit identity."""
    settings = _desktop_settings(tmp_path / "request-identity")
    database = _stamp_database(settings, "0041")
    _add_native_review_table(database)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO review_queue_item_events "
            "(id, review_queue_id, review_queue_item_id, project_id, "
            "client_request_id, event_type, actor, created_at) "
            "VALUES ('first', 'queue-a', 'item-a', 'project-a', "
            "'request-1', 'comment', 'reviewer', '2026-10-29T00:00:00')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            connection.execute(
                "INSERT INTO review_queue_item_events "
                "(id, review_queue_id, review_queue_item_id, project_id, "
                "client_request_id, event_type, actor, created_at) "
                "VALUES ('duplicate', 'queue-a', 'item-a', 'project-a', "
                "'request-1', 'comment', 'reviewer', '2026-10-29T00:00:00')"
            )
        # Request identities are scoped to an item, not globally to a queue.
        connection.execute(
            "INSERT INTO review_queue_item_events "
            "(id, review_queue_id, review_queue_item_id, project_id, "
            "client_request_id, event_type, actor, created_at) "
            "VALUES ('other-item', 'queue-a', 'item-b', 'project-a', "
            "'request-1', 'comment', 'reviewer', '2026-10-29T00:00:00')"
        )
        saved_events = connection.execute(
            "SELECT COUNT(*) FROM review_queue_item_events"
        ).fetchone()[0]
        assert saved_events == 2



@pytest.mark.parametrize(
    "missing_field",
    [
        "id",
        "review_queue_id",
        "review_queue_item_id",
        "project_id",
        "client_request_id",
        "event_type",
        "actor",
        "created_at",
    ],
)
def test_synthetic_0041_fixture_rejects_missing_reviewer_provenance(
    tmp_path: Path, missing_field: str
) -> None:
    """A positive startup fixture must not silently accept missing audit data."""
    settings = _desktop_settings(tmp_path / f"missing-{missing_field}")
    database = _stamp_database(settings, "0041")
    _add_native_review_table(database)

    evidence = {
        "id": "event-1",
        "review_queue_id": "queue-1",
        "review_queue_item_id": "item-1",
        "project_id": "project-1",
        "client_request_id": "request-1",
        "event_type": "comment",
        "actor": "researcher",
        "created_at": "2026-10-29T00:00:00",
    }
    del evidence[missing_field]
    columns = ", ".join(evidence)
    placeholders = ", ".join("?" for _ in evidence)
    with sqlite3.connect(database) as connection:
        original_schema = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'review_queue_item_events'"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed"):
            connection.execute(
                f"INSERT INTO review_queue_item_events ({columns}) VALUES ({placeholders})",
                tuple(evidence.values()),
            )
        assert connection.execute(
            "SELECT COUNT(*) FROM review_queue_item_events"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'review_queue_item_events'"
        ).fetchone()[0] == original_schema


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
        _add_native_review_table(
            settings.resolved_data_dir / "reefvision.db", revision=current_head
        )

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
