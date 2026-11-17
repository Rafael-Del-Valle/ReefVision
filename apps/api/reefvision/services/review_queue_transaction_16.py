"""Serialize SQLite QC triage before reading queue state or audit events.

Single-item and bulk reviewers share this barrier. It never changes source
images, annotations, persisted QC scores, or saved Workflow Builder graphs.
"""

from __future__ import annotations

import sqlite3

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reefvision.domain.errors import ConflictError


def begin_serialized_review_triage(session: Session) -> None:
    """Claim the SQLite writer turn before checking a review transition.

    Deferred read-first transactions can inspect an outdated state, then wait
    for another reviewer to commit. An immediate transaction makes the state
    check and the append-only review event one serialized decision. The helper
    is called before any query, including idempotent replay lookups.
    """
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    if getattr(connection.connection.driver_connection, "in_transaction", False):
        raise ConflictError(
            "Review triage requires a fresh transaction; retry after reloading the queue"
        )
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    except OperationalError as exc:
        session.rollback()
        raw = exc.orig
        code = getattr(raw, "sqlite_errorcode", None)
        if (
            isinstance(raw, sqlite3.OperationalError)
            and isinstance(code, int)
            and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
        ):
            raise ConflictError(
                "SQLite review queue is busy; retry the same bulk request ID after it clears"
            ) from exc
        raise
