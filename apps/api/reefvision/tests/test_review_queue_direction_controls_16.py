"""Reject invisible direction controls in QC reviewer *labels*, not natural scripts.

Executable saved-graph and standalone queues share the same historical
review guard. Every database mutation below is confined to pytest fixtures.
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
    ("field", "control"),
    [("actor", "\u202e"), ("assignee", "\u2067")],
)
def test_imported_direction_control_blocks_history_and_all_reviewer_paths(
    client: TestClient, saved_workflow: bool, field: str, control: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "marine researcher",
        "assignee": "reviewer-two",
    }
    created = client.post(url, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    tampered = "scientist" + control + "other"
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        original = getattr(event, field)
        setattr(event, field, tampered)
        session.commit()

    history = client.get(url, params={"page": 999, "page_size": 1})
    manual = client.post(url, json={**payload, "client_request_id": str(uuid4())})
    bulk = client.post(
        f"/api/v1/review-queues/{queue_id}/items/bulk",
        json={
            "item_ids": item_ids,
            "action": "start",
            "actor": "marine researcher",
            "client_request_id": str(uuid4()),
        },
    )
    single = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    for response in (history, manual, bulk, single):
        assert response.status_code == 409, response.text
        assert "inconsistent action evidence" in response.text
        assert tampered not in response.text

    pending = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert pending.status_code == 200, pending.text
    assert {item["review_state"] for item in pending.json()["items"]} == {"pending"}
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
        assert getattr(event, field) == tampered
        # Explicit repair is test-fixture-only, never a production auto-fix.
        setattr(event, field, original)
        session.commit()

    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["requires_researcher_review"] is True
    replay = client.post(url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == event_id


@pytest.mark.parametrize("control", ["\u202d", "\u2066"])
def test_manual_single_and_bulk_inputs_reject_spoofed_actor_labels(
    client: TestClient, control: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=False)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "marine researcher",
        "assignee": "reviewer-two",
    }
    label = "researcher" + control + "other"
    rejected = [
        client.post(url, json={**payload, "actor": label}),
        client.post(url, json={**payload, "assignee": label}),
        client.post(f"/api/v1/review-queue-items/{item_id}/start", json={"actor": label}),
        client.post(
            f"/api/v1/review-queues/{queue_id}/items/bulk",
            json={"item_ids": item_ids, "action": "start", "actor": label},
        ),
    ]
    assert all(response.status_code == 422 for response in rejected), [
        (response.status_code, response.text) for response in rejected
    ]
    pending = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert pending.status_code == 200, pending.text
    assert {item["review_state"] for item in pending.json()["items"]} == {"pending"}

    # Natural right-to-left script is supported; only directional controls
    # in the self-reported name are rejected.
    accepted = client.post(
        url,
        json={**payload, "actor": "باحث", "assignee": "مراجع"},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["actor"] == "باحث"
    assert accepted.json()["assignee"] == "مراجع"
    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["requires_researcher_review"] is True
