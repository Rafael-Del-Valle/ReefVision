"""Fail closed on imported malformed QC request UUIDs and preserve human review.

A canonical client request key is part of the original audit provenance, not
an arbitrary TEXT field. Exercise both standalone and *executed persisted*
Workflow Builder QC queues with disposable SQLite databases only.
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
    "tampered_request_id",
    [
        "abcdef12-3456-4abc-8def-abcdef12345",
        "ABCDEF12-3456-4ABC-8DEF-ABCDEF123456",
        "abcdef1234564abc8defabcdef123456",
        "abcdef12-3456-4abc-8def-abcdef12345g",
        "abcdef12-3456_4abc-8def-abcdef123456",
        "abcdef12-3456-4abc-8def-abcdef123456\x00hidden",
    ],
)
def test_imported_noncanonical_request_id_blocks_all_review_paths_and_recovery(
    client: TestClient, saved_workflow: bool, tampered_request_id: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    events_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "coral reviewer",
        "assignee": "second reviewer",
    }
    created = client.post(events_url, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        original_request_id = event.client_request_id
        assert original_request_id == payload["client_request_id"]
        event.client_request_id = tampered_request_id
        session.commit()

    # An invalid off-page key must not be presented as trustworthy audit
    # history, reused by a matching request, or bypassed with a new key.
    requests = [
        client.get(events_url, params={"page": 999, "page_size": 1}),
        client.post(events_url, json=payload),
        client.post(
            events_url,
            json={
                **payload,
                "client_request_id": str(uuid4()),
                "event_type": "comment",
                "comment": "Recheck the branch margin",
                "assignee": None,
            },
        ),
        client.post(f"/api/v1/review-queue-items/{item_id}/start"),
    ]
    batch_payload = {
        "item_ids": item_ids,
        "action": "start",
        "actor": "coral reviewer",
        "client_request_id": str(uuid4()),
    }
    batch_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    requests.append(client.post(batch_url, json=batch_payload))
    for response in requests:
        assert response.status_code == 409, response.text
        assert "inconsistent action evidence" in response.text
        assert tampered_request_id not in response.text

    listing = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert listing.status_code == 200, listing.text
    assert {item["review_state"] for item in listing.json()["items"]} == {"pending"}
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReviewQueueItemEvent)
                .where(ReviewQueueItemEvent.review_queue_item_id.in_(item_ids))
            )
            == 1
        )
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        assert event.client_request_id == tampered_request_id
        # Repair ONLY the disposable test fixture, never production evidence.
        event.client_request_id = original_request_id
        session.commit()

    recovered_history = client.get(events_url)
    assert recovered_history.status_code == 200, recovered_history.text
    assert recovered_history.json()["requires_researcher_review"] is True
    assert recovered_history.json()["current_assignee"] == "second reviewer"
    assert recovered_history.json()["total"] == 1

    replay = client.post(events_url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == event_id
    committed = client.post(batch_url, json=batch_payload)
    assert committed.status_code == 200, committed.text
    assert committed.json()["changed_count"] == len(item_ids)
    assert committed.json()["requires_researcher_review"] is True
    repeated = client.post(batch_url, json=batch_payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["changed_count"] == 0
