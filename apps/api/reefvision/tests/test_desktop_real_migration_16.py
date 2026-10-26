"""Real SQLite desktop-migration regression for the isolated 1.6 lineage.

Unlike mocked migration tests, this exercises Alembic's env.py, all revision
scripts, and the database that the desktop opens again after upgrading.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from reefvision.config import Settings
from reefvision.db.session import create_database_engine
from reefvision.desktop import resolve_alembic_paths, run_pending_migrations


def test_desktop_fresh_sqlite_migration_persists_revision_across_restarts(
    tmp_path: Path,
) -> None:
    database = tmp_path / "real-desktop-migration.sqlite"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{database.as_posix()}",
    )
    settings.ensure_directories()

    run_pending_migrations(settings)

    # A new engine must see the Alembic revision and the 1.6 review table.
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
            assert inspect(connection).has_table("review_queue_bulk_requests")
    finally:
        engine.dispose()

    # An already-migrated installed desktop must not reset or repeat revisions.
    run_pending_migrations(settings)

    reopened_engine = create_database_engine(settings)
    try:
        with reopened_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
    finally:
        reopened_engine.dispose()


def test_review_revision_roundtrip_commits_sqlite_version_markers(tmp_path: Path) -> None:
    """Real Alembic downgrade/re-upgrade must persist revision DML on SQLite.

    SQLite DDL may persist independently of a rolled-back alembic_version
    update, so checking only for the presence of tables misses this regression.
    """
    database = tmp_path / "roundtrip.sqlite"
    settings = Settings(data_dir=tmp_path, database_url=f"sqlite:///{database.as_posix()}")
    settings.ensure_directories()
    run_pending_migrations(settings)

    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = settings.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.downgrade(config, "0037")

    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0037"
            assert not inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()

    run_pending_migrations(settings)
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0041"
            assert inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()
