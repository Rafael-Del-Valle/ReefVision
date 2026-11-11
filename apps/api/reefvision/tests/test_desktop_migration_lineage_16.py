"""Desktop migration-lineage safety, including the already-at-head fast path."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session


def _prepare_desktop_migration(
    monkeypatch: pytest.MonkeyPatch, engine: object, *, head: str = "0038"
) -> None:
    monkeypatch.setattr(session, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(
        desktop.ScriptDirectory,
        "from_config",
        lambda _config: SimpleNamespace(get_current_head=lambda: head),
    )
    monkeypatch.setattr(
        desktop.command,
        "upgrade",
        lambda *_args, **_kwargs: pytest.fail("Already-at-head must not run upgrade"),
    )


def _create_review_event_parents(connection: object) -> None:
    """Build the three 0038 parent tables for a faithful SQLite QC fixture."""
    for table in ("projects", "review_queues", "review_queue_items"):
        connection.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))


def _create_review_event_history_indexes(connection: object) -> None:
    """Preserve the original ascending, non-unique reviewer history indexes."""
    connection.execute(text(
        "CREATE INDEX ix_review_queue_item_events_item_created "
        "ON review_queue_item_events (review_queue_item_id, created_at)"
    ))
    connection.execute(text(
        "CREATE INDEX ix_review_queue_item_events_queue_created "
        "ON review_queue_item_events (review_queue_id, created_at)"
    ))


@pytest.mark.parametrize("revision", ["0038", "0039", "0040", "0041"])
def test_desktop_rejects_foreign_review_lineage_even_when_at_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revision: str,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(text("CREATE TABLE scientific_records (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO scientific_records VALUES ('preserve-me')"))
    _prepare_desktop_migration(monkeypatch, engine, head=revision)

    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    with pytest.raises(RuntimeError, match=f"Unsafe ReefVision Alembic revision {revision}"):
        desktop.run_pending_migrations(settings)

    # No schema changes or revision stamping are permitted on failure.
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert connection.scalar(text("SELECT id FROM scientific_records")) == "preserve-me"


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
def test_desktop_accepts_native_review_lineage_at_head_without_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revision: str,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        allowed = "'comment', 'assign', 'unassign'"
        if revision in {"0039", "0040", "0041"}:
            allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
        if revision in {"0040", "0041"}:
            allowed += ", 'triage_complete'"
        _create_review_event_parents(connection)
        event_type_check = (
            f", CONSTRAINT ck_review_queue_item_event_type CHECK (event_type IN ({allowed}))"
        )
        connection.execute(
            text(
                "CREATE TABLE review_queue_item_events ("
                "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "review_queue_item_id TEXT NOT NULL, project_id TEXT NOT NULL, "
                "client_request_id TEXT NOT NULL, event_type TEXT NOT NULL, "
                "actor TEXT NOT NULL, comment TEXT, assignee TEXT, "
                "created_at TEXT NOT NULL, "
                "FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE CASCADE, "
                "FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id) ON DELETE CASCADE, "
                "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE, "
                "CONSTRAINT uq_review_queue_item_event_request "
                "UNIQUE (review_queue_item_id, client_request_id)"
                f"{event_type_check})"
            )
        )
        _create_review_event_history_indexes(connection)
        # Create valid parents under enforced SQLite FK constraints.
        for table, parent_id in (
            ("projects", "project-1"),
            ("review_queues", "queue-1"),
            ("review_queue_items", "item-1"),
        ):
            connection.execute(
                text(f"INSERT INTO {table} (id) VALUES (:parent_id)"),
                {"parent_id": parent_id},
            )
        # Already-at-head startup must preserve existing biological QC notes.
        connection.execute(
            text(
                "INSERT INTO review_queue_item_events "
                "(id, review_queue_id, review_queue_item_id, project_id, "
                "client_request_id, event_type, actor, comment, created_at) "
                "VALUES ('event-preserved', 'queue-1', 'item-1', 'project-1', "
                "'request-1', 'comment', 'researcher', "
                "'biological observation', '2026-11-09')"
            )
        )
        if revision == "0041":
            connection.execute(
                text(
                    "CREATE TABLE review_queue_bulk_requests ("
                    "id TEXT PRIMARY KEY, review_queue_id TEXT, project_id TEXT, "
                    "action TEXT, actor TEXT, reason TEXT, item_ids_json TEXT, "
                    "created_at TEXT)"
                )
            )
    _prepare_desktop_migration(monkeypatch, engine, head=revision)

    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    desktop.run_pending_migrations(settings)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert connection.execute(
            text("SELECT id, comment FROM review_queue_item_events")
        ).one() == ("event-preserved", "biological observation")


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
def test_desktop_rejects_defaulted_audit_event_type_at_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revision: str,
) -> None:
    """An already-at-head stamp cannot bypass the explicit-event contract."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    allowed = "'comment', 'assign', 'unassign'"
    if revision in {"0039", "0040", "0041"}:
        allowed += ", 'triage_start', 'triage_skip', 'triage_return'"
    if revision in {"0040", "0041"}:
        allowed += ", 'triage_complete'"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(text("CREATE TABLE preserved (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO preserved VALUES ('original-research')"))
        connection.execute(
            text(
                "CREATE TABLE review_queue_item_events ("
                "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                "review_queue_item_id TEXT NOT NULL, project_id TEXT NOT NULL, "
                "client_request_id TEXT NOT NULL, "
                "event_type TEXT NOT NULL DEFAULT 'comment', actor TEXT NOT NULL, "
                "comment TEXT, assignee TEXT, created_at TEXT NOT NULL, "
                "CONSTRAINT uq_review_queue_item_event_request "
                "UNIQUE (review_queue_item_id, client_request_id), "
                "CONSTRAINT ck_review_queue_item_event_type "
                f"CHECK (event_type IN ({allowed})))"
            )
        )
        connection.execute(
            text("INSERT INTO review_queue_item_events "
                "(id, review_queue_id, review_queue_item_id, project_id, "
                "client_request_id, actor, created_at) "
                "VALUES ('forged-comment', 'queue-1', 'item-1', 'project-1', "
                "'request-1', 'researcher', '2026-11-09')")
        )
    _prepare_desktop_migration(monkeypatch, engine, head=revision)
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    with pytest.raises(RuntimeError, match="unexpected server default"):
        desktop.run_pending_migrations(settings)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
        assert connection.scalar(text("SELECT id FROM preserved")) == "original-research"
        assert (
            connection.scalar(text("SELECT event_type FROM review_queue_item_events")) == "comment"
        )
    engine.dispose()


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


def test_desktop_rejects_unversioned_populated_database_before_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lineage.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE preserved (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO preserved VALUES ('retain-me')"))
    observed_urls: list[str] = []

    def no_op_upgrade(config: Config, _revision: str) -> None:
        observed_urls.append(config.attributes["desktop_database_url"])

    _prepare_fresh_desktop_migration(monkeypatch, engine, upgrade=no_op_upgrade)

    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    with pytest.raises(RuntimeError, match="Unsafe ReefVision unversioned populated database"):
        desktop.run_pending_migrations(settings)

    assert observed_urls == []
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
            _create_review_event_parents(connection)
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT NOT NULL PRIMARY KEY, review_queue_id TEXT NOT NULL, "
                    "review_queue_item_id TEXT NOT NULL, project_id TEXT NOT NULL, "
                    "client_request_id TEXT NOT NULL, event_type TEXT NOT NULL, "
                    "actor TEXT NOT NULL, comment TEXT, assignee TEXT, "
                    "created_at TEXT NOT NULL, "
                    "FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE CASCADE, "
                    "FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id) ON DELETE CASCADE, "
                    "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE, "
                    "CONSTRAINT uq_review_queue_item_event_request "
                    "UNIQUE (review_queue_item_id, client_request_id), "
                    "CONSTRAINT ck_review_queue_item_event_type "
                    "CHECK (event_type IN ('comment', 'assign', 'unassign')))"
                )
            )

            _create_review_event_history_indexes(connection)

    _prepare_fresh_desktop_migration(monkeypatch, engine, upgrade=apply_native_review_revision)
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    desktop.run_pending_migrations(settings)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
