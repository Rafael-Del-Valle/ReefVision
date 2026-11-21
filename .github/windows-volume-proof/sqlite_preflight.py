"""Prepare the existing journal mode without changing application settings."""

import sqlite3
from contextlib import closing
from pathlib import Path


def prepare_for_capacity_pressure(database: Path) -> dict[str, int | str | bool | None]:
    """Check a prepared, otherwise idle fixture before applying disk pressure."""
    uri = database.resolve(strict=True).as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
        (mode,) = connection.execute("PRAGMA journal_mode").fetchone()
        if mode == "wal":
            status = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if status != (0, 0, 0):
                raise RuntimeError(f"Could not truncate the prepared SQLite WAL: {status!r}")
        elif mode == "delete":
            # Acquire and release an ordinary writer lock without making any writes.
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        else:
            raise RuntimeError(f"Unsupported SQLite journal mode: {mode!r}")

    wal = database.with_suffix(".db-wal")
    if wal.exists() and wal.stat().st_size:
        raise RuntimeError("The capacity fixture has a nonempty SQLite WAL")

    rollback_journal = database.with_suffix(".db-journal")
    if mode == "delete" and rollback_journal.exists() and rollback_journal.stat().st_size:
        raise RuntimeError("The capacity fixture has a nonempty SQLite rollback journal")

    return {
        "journal_mode": mode,
        "sqlite_wal_checkpoint_truncated": True if mode == "wal" else None,
        "rollback_writer_idle": True if mode == "delete" else None,
        "db_bytes_before_fill": database.stat().st_size,
    }
