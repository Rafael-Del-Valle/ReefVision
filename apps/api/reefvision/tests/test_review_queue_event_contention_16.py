"""Manual QC coordination must preserve audit history under SQLite contention.

Run against disposable databases for both standalone queues and persisted,
executable Workflow Builder QC queues. No annotation is automatically verified.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.schemas.review_queue_events import ReviewQueueEventResponse
from reefvision.services.review_queue_events import _is_sqlite_event_request_collision
from reefvision.tests.test_review_queue_bulk_sqlite_contention_16 import _make_queue


def _real_constraint(statement: str) -> IntegrityError:
    """Construct a real SQLite extended error code rather than fake text."""
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE review_queue_item_events (
                review_queue_item_id TEXT NOT NULL,
                client_request_id TEXT NOT NULL,
                UNIQUE (review_queue_item_id, client_request_id)
            );
            INSERT INTO review_queue_item_events VALUES ('item', 'request');
            CREATE TABLE unrelated_science (name TEXT UNIQUE, count INTEGER NOT NULL);
            INSERT INTO unrelated_science VALUES ('original', 1);
            CREATE TABLE referenced_science (
                parent_id INTEGER REFERENCES missing_parent(id)
            );
            CREATE TABLE missing_parent (id INTEGER PRIMARY KEY);
            """
        )
        try:
            connection.execute(statement)
        except sqlite3.IntegrityError as exc:
            return IntegrityError(statement, {}, exc)
    raise AssertionError("Expected an actual SQLite constraint violation")


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("INSERT INTO review_queue_item_events VALUES ('item', 'request')", True),
        ("INSERT INTO unrelated_science VALUES ('original', 2)", False),
        ("INSERT INTO unrelated_science VALUES ('other', NULL)", False),
        ("INSERT INTO referenced_science VALUES (99)", False),
    ],
)
def test_only_coordination_event_identity_collision_is_retryable(
    statement: str, expected: bool
) -> None:
    error = _real_constraint(statement)
    assert _is_sqlite_event_request_collision(error) is expected
    assert not _is_sqlite_event_request_collision(
        IntegrityError(statement, {}, RuntimeError("UNIQUE constraint failed"))
    )


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize("lock_mode", ["IMMEDIATE", "EXCLUSIVE"])
def test_manual_event_lock_rolls_back_and_same_request_retries(
    client: TestClient, saved_workflow: bool, lock_mode: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "local researcher",
        "assignee": "reviewer-two",
    }
    app = cast(FastAPI, client.app)
    db_path = make_url(app.state.settings.resolved_database_url).database
    assert db_path is not None and Path(db_path).is_file()

    blocker = sqlite3.connect(db_path, timeout=0.2, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE" if lock_mode == "IMMEDIATE" else "BEGIN EXCLUSIVE")
        blocked = client.post(url, json=payload)
        assert blocked.status_code == 409, blocked.text
        assert "busy" in blocked.text.lower()
    finally:
        blocker.rollback()
        blocker.close()

    untouched = client.get(url)
    assert untouched.status_code == 200, untouched.text
    assert untouched.json()["total"] == 0
    assert untouched.json()["current_assignee"] is None

    created = client.post(url, json=payload)
    assert created.status_code == 201, created.text
    replay = client.post(url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == created.json()["id"]
    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["current_assignee"] == "reviewer-two"
    assert history.json()["requires_researcher_review"] is True
    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    assert {item["review_state"] for item in items.json()["items"]} == {"pending"}
    image_id = next(item["image_id"] for item in items.json()["items"] if item["id"] == item_id)
    annotations = client.get(f"/api/v1/images/{image_id}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_locked_review_history_read_is_retryable_and_preserves_evidence(
    client: TestClient, saved_workflow: bool
) -> None:
    """An EXCLUSIVE local writer must not turn QC history reads into HTTP 500."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    url = f"/api/v1/review-queues/{queue_id}/items/{item_ids[0]}/events"
    app = cast(FastAPI, client.app)
    db_path = make_url(app.state.settings.resolved_database_url).database
    assert db_path is not None and Path(db_path).is_file()

    blocker = sqlite3.connect(db_path, timeout=0.2, isolation_level=None)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        blocked = client.get(url)
        assert blocked.status_code == 409, blocked.text
        assert "busy" in blocked.text.lower()
    finally:
        blocker.rollback()
        blocker.close()

    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 0
    assert history.json()["items"] == []
    assert history.json()["current_assignee"] is None
    assert history.json()["requires_researcher_review"] is True
    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    assert {item["review_state"] for item in items.json()["items"]} == {"pending"}


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_unrelated_event_integrity_failure_propagates_without_audit_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, saved_workflow: bool
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    url = f"/api/v1/review-queues/{queue_id}/items/{item_ids[0]}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "comment",
        "actor": "local researcher",
        "comment": "Inspect coral branch tips",
    }
    unrelated = _real_constraint("INSERT INTO unrelated_science VALUES ('original', 2)")
    real_commit = Session.commit

    def fail_unrelated_commit(session: Session) -> None:
        if any(isinstance(obj, ReviewQueueItemEvent) for obj in session.new):
            raise unrelated
        real_commit(session)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_unrelated_commit)
        with pytest.raises(IntegrityError):
            client.post(url, json=payload)

    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 0
    committed = client.post(url, json=payload)
    assert committed.status_code == 201, committed.text
    replay = client.post(url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == committed.json()["id"]
    assert client.get(url).json()["total"] == 1


@pytest.mark.parametrize(
    "stored_timestamp",
    ["2026-10-29T00:00:00", "2026-10-29T02:00:00+02:00"],
)
def test_reviewer_audit_schema_normalizes_legacy_and_offset_timestamps(
    stored_timestamp: str,
) -> None:
    """Older SQLite timestamps are UTC even if the driver drops tzinfo."""
    event = ReviewQueueEventResponse.model_validate(
        {
            "id": str(uuid4()),
            "review_queue_id": str(uuid4()),
            "review_queue_item_id": str(uuid4()),
            "project_id": str(uuid4()),
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "local researcher",
            "comment": "Inspect branching",
            "assignee": None,
            "created_at": stored_timestamp,
        }
    )
    assert event.created_at == datetime(2026, 10, 29, tzinfo=UTC)
    assert event.model_dump(mode="json")["created_at"].endswith("Z")


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_manual_review_history_has_explicit_utc_provenance(
    client: TestClient, saved_workflow: bool
) -> None:
    """API and saved Workflow Builder QC histories agree on UTC evidence."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    url = f"/api/v1/review-queues/{queue_id}/items/{item_ids[0]}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "comment",
        "actor": "local researcher",
        "comment": "Inspect coral polyp boundaries",
    }
    created = client.post(url, json=payload)
    assert created.status_code == 201, created.text
    replay = client.post(url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == created.json()["id"]

    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["requires_researcher_review"] is True
    assert history.json()["total"] == 1
    for response in (created.json(), replay.json(), history.json()["items"][0]):
        timestamp = datetime.fromisoformat(response["created_at"].replace("Z", "+00:00"))
        assert timestamp.tzinfo is not None
        assert timestamp.utcoffset() == UTC.utcoffset(None)
        assert response["created_at"].endswith("Z")
    assert history.json()["items"][0]["id"] == created.json()["id"]

    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    assert {item["review_state"] for item in items.json()["items"]} == {"pending"}
