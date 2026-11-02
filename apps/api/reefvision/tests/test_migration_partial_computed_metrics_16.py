"""Refuse partially applied 1.1 computed-metric DDL before 1.6 desktop writes.

The 1.1 scientific revision 0039 creates two tables independently. SQLite can
retain either table after a failed migration even when its 0038 tables and
Alembic version marker are absent. Protect saved calculations and provenance.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from reefvision import desktop
from reefvision.db import session
from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.fixture(params=["computed_metric_definitions", "computed_metric_results"])
def metric_table(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _seed_partial_metrics(engine: object, revision: str | None, metric_table: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE observations (id TEXT PRIMARY KEY, value TEXT)"))
        connection.execute(
            text("INSERT INTO observations VALUES ('coral-1', 'preserved biological data')")
        )
        if revision is not None:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
        if revision in {"0038", "0039", "0040"}:
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
        # Deliberately only one of the two 1.1 metric tables exists, with no
        # scientific_records or environmental_cache_entries. This models an
        # interrupted DDL operation, not a valid cross-version installation.
        connection.execute(text(f"CREATE TABLE {metric_table} (id TEXT PRIMARY KEY)"))
        connection.execute(text(f"INSERT INTO {metric_table} VALUES ('saved-metric')"))


def _snapshot(connection: object, metric_table: str) -> tuple[object, ...]:
    return (
        tuple(
            connection.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
            ).all()
        ),
        tuple(connection.execute(text("SELECT id, value FROM observations")).all()),
        tuple(connection.execute(text(f"SELECT id FROM {metric_table}")).all()),
        tuple(connection.execute(text("SELECT version_num FROM alembic_version")).all())
        if connection.dialect.has_table(connection, "alembic_version")
        else None,
    )


@pytest.mark.parametrize("revision", [None, "0037", "0038", "0039", "0040"])
def test_partial_computed_metrics_refused_without_modifying_science(
    tmp_path: Path, revision: str | None, metric_table: str
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'partial-metrics.sqlite'}")
    _seed_partial_metrics(engine, revision, metric_table)
    with engine.connect() as connection:
        before = _snapshot(connection, metric_table)
    for _ in range(2):
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="scientific tables"):
                assert_compatible_revision_0038(connection)
            assert _snapshot(connection, metric_table) == before
    engine.dispose()


@pytest.mark.parametrize("revision", [None, "0037"])
def test_desktop_never_upgrades_partial_metric_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    revision: str | None,
    metric_table: str,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'desktop-metrics.sqlite'}")
    _seed_partial_metrics(engine, revision, metric_table)
    with engine.connect() as connection:
        before = _snapshot(connection, metric_table)
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
            "An interrupted scientific metric migration must never run Alembic upgrade"
        ),
    )
    settings = SimpleNamespace(resolved_database_url=str(engine.url))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="scientific tables"):
            desktop.run_pending_migrations(settings)
        with engine.connect() as connection:
            assert _snapshot(connection, metric_table) == before
    engine.dispose()
