"""Real SQLite desktop-migration regression for the isolated 1.6 lineage.

Unlike mocked migration tests, this exercises Alembic's env.py, all revision
scripts, and the database that the desktop opens again after upgrading.
"""

from pathlib import Path

from sqlalchemy import inspect, text

from reefvision.config import Settings
from reefvision.db.session import create_database_engine
from reefvision.desktop import run_pending_migrations


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
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
            assert inspect(connection).has_table("review_queue_item_events")
    finally:
        engine.dispose()

    # An already-migrated installed desktop must not reset or repeat revisions.
    run_pending_migrations(settings)

    reopened_engine = create_database_engine(settings)
    try:
        with reopened_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0038"
            assert inspect(connection).has_table("review_queue_item_events")
    finally:
        reopened_engine.dispose()
