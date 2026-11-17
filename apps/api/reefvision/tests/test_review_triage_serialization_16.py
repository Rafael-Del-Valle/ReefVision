"""QC review state and event decisions must serialize across local API sessions."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from reefvision.domain.errors import ConflictError
from reefvision.services.review_queue_transaction_16 import begin_serialized_review_triage


def test_reviewer_sees_new_state_only_after_prior_writer_commits(tmp_path: Path) -> None:
    """A rejected simultaneous reviewer cannot append stale or double audit state."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'serialized-review.sqlite'}",
        connect_args={"timeout": 0.02},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE reviewer_state (id INTEGER PRIMARY KEY, state TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE reviewer_events (id INTEGER PRIMARY KEY, action TEXT NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO reviewer_state VALUES (1, 'pending')")

    with Session(engine) as first, Session(engine) as second:
        begin_serialized_review_triage(first)
        assert first.scalar(text("SELECT state FROM reviewer_state WHERE id = 1")) == "pending"
        with pytest.raises(ConflictError, match="busy"):
            begin_serialized_review_triage(second)

        first.execute(text("UPDATE reviewer_state SET state = 'in_progress' WHERE id = 1"))
        first.execute(text("INSERT INTO reviewer_events VALUES (1, 'start')"))
        first.commit()

        begin_serialized_review_triage(second)
        assert second.scalar(text("SELECT state FROM reviewer_state WHERE id = 1")) == "in_progress"
        assert second.scalar(text("SELECT COUNT(*) FROM reviewer_events")) == 1
        second.commit()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT state FROM reviewer_state")) == "in_progress"
        assert connection.scalar(text("SELECT COUNT(*) FROM reviewer_events")) == 1
    engine.dispose()


def test_existing_sqlite_read_transaction_fails_closed(tmp_path: Path) -> None:
    """A reviewer cannot acquire the barrier after reading a possibly stale state."""
    engine = create_engine(f"sqlite:///{tmp_path / 'stale-review.sqlite'}")
    with Session(engine) as session:
        session.connection().exec_driver_sql("BEGIN")
        with pytest.raises(ConflictError, match="fresh transaction"):
            begin_serialized_review_triage(session)
        session.rollback()
        begin_serialized_review_triage(session)
        session.commit()
    engine.dispose()
