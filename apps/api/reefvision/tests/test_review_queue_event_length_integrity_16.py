"""Restored QC review evidence must honor manual API Unicode text limits.

Both standalone queues and persisted, executable Workflow Builder queues
share this read-only scientific audit guard. No observations are approved.
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


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize(
    ("event_type", "field", "oversized"),
    [
        ("comment", "actor", "R" * 101),
        ("comment", "comment", "🐙" * 2001),
        ("assign", "assignee", "é" * 101),
    ],
)
def test_imported_overlength_review_evidence_blocks_all_triage_paths(
    client: TestClient, saved_workflow: bool, event_type: str, field: str, oversized: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    events_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": event_type,
        "actor": "local researcher",
    }
    if event_type == "comment":
        payload["comment"] = "Inspect animal boundaries"
    else:
        payload["assignee"] = "reviewer-two"

    # The public write contract already rejects excessive Unicode strings.
    invalid = client.post(
        events_url,
        json={**payload, field: oversized, "client_request_id": str(uuid4())},
    )
    assert invalid.status_code == 422, invalid.text

    created = client.post(events_url, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        original = getattr(event, field)
        setattr(event, field, oversized)
        session.commit()

    # Every entry point checks entire historical evidence, not only this page.
    history = client.get(events_url, params={"page": 999, "page_size": 1})
    manual = client.post(
        events_url, json={**payload, "client_request_id": str(uuid4())}
    )
    bulk = client.post(
        f"/api/v1/review-queues/{queue_id}/items/bulk",
        json={
            "item_ids": item_ids,
            "action": "start",
            "actor": "local researcher",
            "client_request_id": str(uuid4()),
        },
    )
    single = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    for rejected in (history, manual, bulk, single):
        assert rejected.status_code == 409, rejected.text
        assert "inconsistent action evidence" in rejected.text
        assert oversized not in rejected.text

    queue_items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert queue_items.status_code == 200, queue_items.text
    assert {item["review_state"] for item in queue_items.json()["items"]} == {"pending"}

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReviewQueueItemEvent)
                .where(ReviewQueueItemEvent.review_queue_item_id == item_id)
            )
            == 1
        )
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        assert getattr(event, field) == oversized
        # Restore only an isolated disposable regression fixture.
        setattr(event, field, original)
        session.commit()

    history = client.get(events_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["requires_researcher_review"] is True
    replay = client.post(events_url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == event_id
