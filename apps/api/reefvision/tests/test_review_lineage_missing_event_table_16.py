"""Fail-closed recovery for a stamped QC revision missing its audit table.

A restored 0038-0040 database must never be treated as an empty QC lineage.
These are read-only migration-preflight regressions, not repair procedures.
"""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.migration_lineage_guard import assert_compatible_revision_0038


@pytest.mark.parametrize("revision", ["0038", "0039", "0040"])
def test_stamped_review_revision_without_event_table_preserves_biology(
    revision: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": revision},
            )
            connection.execute(
                text(
                    "CREATE TABLE observations (id TEXT PRIMARY KEY, measurement REAL NOT NULL)"
                )
            )
            connection.execute(
                text("INSERT INTO observations VALUES ('coral-1', 12.5)")
            )
            before = tuple(connection.execute(text("SELECT * FROM observations")).all())
            for _ in range(2):
                with pytest.raises(
                    RuntimeError, match="not the ReefVision 1.6 review-events lineage"
                ):
                    assert_compatible_revision_0038(connection)
                assert (
                    tuple(connection.execute(text("SELECT * FROM observations")).all())
                    == before
                )
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
                )
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM sqlite_master WHERE type='table' "
                        "AND name='review_queue_item_events'"
                    )
                ) == 0
    finally:
        engine.dispose()
