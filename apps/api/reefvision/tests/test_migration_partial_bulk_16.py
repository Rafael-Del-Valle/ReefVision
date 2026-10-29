"""Fail-closed desktop preflight for interrupted 1.6 QC revision 0041.

The 0041 migration creates a persistent global bulk-review request registry.
A crash between table creation and Alembic stamping can leave 0038-0040
recorded while the new table already exists. Never replay 0041 blindly.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


def _seed_interrupted_bulk_registry(engine: object, revision: str, *, populated: bool) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(text("CREATE TABLE observations (id TEXT PRIMARY KEY, value TEXT)"))
        connection.execute(
            text("INSERT INTO observations VALUES ('coral-1', 'unmodified observation')")
        )
        allowed = "'comment', 'assign', 'unassign'"
        if revision in {"0039", "0040"}:
            allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
        if revision == "0040":
            allowed += ", 'triage_complete'"
        connection.execute(
            text(
                "CREATE TABLE review_queue_item_events ("
                "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
                "project_id TEXT, client_request_id TEXT, event_type TEXT NOT NULL, "
                "actor TEXT, comment TEXT, assignee TEXT, created_at TEXT, "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events (id, event_type, actor) "
                "VALUES ('event-1', 'comment', 'reviewer')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE review_queue_bulk_requests ("
                "id TEXT PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "project_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, "
                "reason TEXT, item_ids_json TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
        )
        if populated:
            connection.execute(
                text(
                    "INSERT INTO review_queue_bulk_requests VALUES "
                    "('request-1', 'queue-1', 'project-1', 'start', 'reviewer', "
                    "NULL, '[\"item-1\"]', '2026-10-29T12:00:00')"
                )
            )


def _snapshot(connection: object) -> tuple[object, ...]:
    schema = tuple(
        connection.execute(
            text("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
        ).all()
    )
    return (
        schema,
        connection.scalar(text("SELECT version_num FROM alembic_version")),
        connection.scalar(text("SELECT value FROM observations WHERE id='coral-1'")),
        tuple(connection.execute(text("SELECT id, actor FROM review_queue_item_events")).all()),
        tuple(connection.execute(text("SELECT id, actor FROM review_queue_bulk_requests")).all()),
    )


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
@pytest.mark.parametrize("populated", [False, True])
def test_interrupted_0041_bulk_table_refused_without_any_data_change(
    tmp_path: Path, revision: str, populated: bool
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'partial.sqlite'}")
    _seed_interrupted_bulk_registry(engine, revision, populated=populated)
    with engine.connect() as connection:
        original = _snapshot(connection)
    for _ in range(2):
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="unexpected bulk-request registry"):
                assert_compatible_revision_0038(connection)
            assert _snapshot(connection) == original
    engine.dispose()


def test_desktop_refuses_partial_bulk_before_alembic_upgrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'desktop.sqlite'}")
    _seed_interrupted_bulk_registry(engine, "0040", populated=True)
    with engine.connect() as connection:
        original = _snapshot(connection)
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
            "Unsafe interrupted migration must never execute Alembic upgrade"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="unexpected bulk-request registry"):
            desktop.run_pending_migrations(settings)
        with engine.connect() as connection:
            assert _snapshot(connection) == original
    engine.dispose()
