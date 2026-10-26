"""Runtime SQLite connections must enforce the QC registry's RESTRICT links."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from reefvision.config import Settings
from reefvision.db.session import create_database_engine


def test_runtime_sqlite_rejects_orphans_and_preserves_referenced_evidence(
    test_settings: Settings,
) -> None:
    """Declared foreign keys must actually protect review history on disk."""
    engine = create_database_engine(test_settings)
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            connection.execute(text("CREATE TABLE fk_parent_16 (id TEXT PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE fk_review_16 ("
                    "id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, "
                    "FOREIGN KEY(parent_id) REFERENCES fk_parent_16(id) "
                    "ON DELETE RESTRICT)"
                )
            )
            connection.execute(text("INSERT INTO fk_parent_16 VALUES ('research-parent')"))
            connection.execute(
                text("INSERT INTO fk_review_16 VALUES ('review-evidence', 'research-parent')")
            )

        with (
            pytest.raises(IntegrityError),
            engine.begin() as connection,
        ):
            connection.execute(
                text("DELETE FROM fk_parent_16 WHERE id = 'research-parent'")
            )

        with (
            pytest.raises(IntegrityError),
            engine.begin() as connection,
        ):
            connection.execute(
                text("INSERT INTO fk_review_16 VALUES ('orphan', 'missing-parent')")
            )

        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM fk_parent_16")) == 1
            assert connection.scalar(text("SELECT COUNT(*) FROM fk_review_16")) == 1
    finally:
        engine.dispose()


def test_sqlite_foreign_keys_remain_enabled_after_pool_reconnect(
    test_settings: Settings,
) -> None:
    """Every new physical SQLite connection must have FK enforcement enabled."""
    engine = create_database_engine(test_settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        engine.dispose()
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()


def test_sqlite_foreign_keys_recover_after_pooled_connection_is_disabled(
    test_settings: Settings,
) -> None:
    """A reused connection must not retain an unsafe local PRAGMA setting."""
    engine = create_database_engine(test_settings)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1

        raw_connection = engine.raw_connection()
        try:
            cursor = raw_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=OFF")
                assert cursor.execute("PRAGMA foreign_keys").fetchone() == (0,)
            finally:
                cursor.close()
        finally:
            raw_connection.close()

        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()
