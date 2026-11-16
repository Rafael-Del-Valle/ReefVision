"""Single-item QC transitions cannot bypass the shared audit-integrity gate.

Both standalone queues and persisted executable Workflow Builder QC queues
are exercised against disposable SQLite fixtures. No biological observations
are approved, repaired, or modified by these tests.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.tests.test_review_queue_bulk_sqlite_contention_16 import _make_queue


def _review_item(client: TestClient, queue_id: str, item_id: str) -> dict:
    response = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["items"] if row["id"] == item_id)


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize("action", ["start", "skip", "return", "complete"])
def test_single_item_triage_rejects_corrupt_existing_history(
    client: TestClient, saved_workflow: bool, action: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    route = f"/api/v1/review-queue-items/{item_id}"
    event_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    if action == "return":
        prepared = client.post(f"{route}/skip", json={"reason": "Unclear coral polyp"})
        assert prepared.status_code == 200, prepared.text

    comment = client.post(
        event_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "local researcher",
            "comment": "Review ambiguous coral tissue",
        },
    )
    assert comment.status_code == 201, comment.text
    payload: dict = {}
    if action == "skip":
        payload = {"reason": "Image outside focus"}
    elif action == "complete":
        payload = {"review_confirmed": True}

    before = _review_item(client, queue_id, item_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, comment.json()["id"])
        assert event is not None
        event.comment = " \t\n"
        total_before = session.scalar(
            select(func.count())
            .select_from(ReviewQueueItemEvent)
            .where(ReviewQueueItemEvent.review_queue_item_id == item_id)
        )
        session.commit()

    rejected = client.post(f"{route}/{action}", json=payload)
    assert rejected.status_code == 409, rejected.text
    assert "inconsistent action evidence" in rejected.text
    assert "ambiguous coral tissue" not in rejected.text
    after = _review_item(client, queue_id, item_id)
    assert after["review_state"] == before["review_state"]
    assert after["completed_at"] == before["completed_at"]
    assert after["skip_reason"] == before["skip_reason"]

    with app.state.session_factory() as session:
        total_after = session.scalar(
            select(func.count())
            .select_from(ReviewQueueItemEvent)
            .where(ReviewQueueItemEvent.review_queue_item_id == item_id)
        )
        assert total_after == total_before
        event = session.get(ReviewQueueItemEvent, comment.json()["id"])
        assert event is not None
        assert event.comment == " \t\n"
        # Only a disposable test record is restored, never user research data.
        event.comment = "Review ambiguous coral tissue"
        session.commit()

    restored = client.post(f"{route}/{action}", json=payload)
    assert restored.status_code == 200, restored.text
    assert restored.json()["review_state"] == {
        "start": "in_progress",
        "skip": "skipped",
        "return": "pending",
        "complete": "completed",
    }[action]
    history = client.get(event_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == total_before + 1
    assert history.json()["requires_researcher_review"] is True
    assert history.json()["items"][-1]["event_type"] == f"triage_{action}"

    annotations = client.get(f"/api/v1/images/{before['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_single_item_triage_rejects_foreign_queue_audit_provenance(
    client: TestClient, saved_workflow: bool
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    foreign_queue_id, _ = _make_queue(client, saved_workflow=False)
    item_id = item_ids[0]
    event_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    added = client.post(
        event_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "assign",
            "actor": "local researcher",
            "assignee": "private-reviewer",
        },
    )
    assert added.status_code == 201, added.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, added.json()["id"])
        assert event is not None
        event.review_queue_id = foreign_queue_id
        session.commit()

    before = _review_item(client, queue_id, item_id)
    blocked = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    assert blocked.status_code == 409, blocked.text
    assert "provenance" in blocked.text
    assert "private-reviewer" not in blocked.text
    assert _review_item(client, queue_id, item_id)["review_state"] == "pending"

    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent).where(
                    ReviewQueueItemEvent.review_queue_item_id == item_id
                )
            )
        )
        assert len(events) == 1
        assert events[0].review_queue_id == foreign_queue_id
        events[0].review_queue_id = queue_id
        session.commit()

    retry = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    assert retry.status_code == 200, retry.text
    assert retry.json()["review_state"] == "in_progress"
    assert retry.json()["requires_researcher_review"] is True
    annotations = client.get(f"/api/v1/images/{before['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []
