"""NUL-containing reviewer evidence must not bypass SQLite TEXT length guards.

Test standalone QC and persisted, executable saved Workflow Builder QC using
disposable database fixtures. No biological observations are approved.
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
    ("event_type", "field", "corrupt_value"),
    [
        ("comment", "actor", "R\x00" + "e" * 120),
        ("comment", "comment", "Inspect\x00" + "c" * 2100),
        ("assign", "assignee", "reviewer\x00" + "x" * 110),
    ],
)
def test_imported_nul_evidence_blocks_history_triage_and_keyed_retry(
    client: TestClient,
    saved_workflow: bool,
    event_type: str,
    field: str,
    corrupt_value: str,
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    history_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": event_type,
        "actor": "local researcher",
    }
    if event_type == "comment":
        payload["comment"] = "Inspect coral boundary"
    else:
        payload["assignee"] = "researcher-two"

    created = client.post(history_url, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        original = getattr(event, field)
        setattr(event, field, corrupt_value)
        session.commit()

        # SQLite LENGTH stops at NUL; the historical size guard alone
        # would incorrectly see a valid short label.
        measured = session.scalar(
            select(func.length(getattr(ReviewQueueItemEvent, field))).where(
                ReviewQueueItemEvent.id == event_id
            )
        )
        assert measured is not None and measured < 100

    batch_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    batch = {
        "item_ids": item_ids,
        "action": "start",
        "actor": "local researcher",
        "client_request_id": str(uuid4()),
    }
    history = client.get(history_url, params={"page": 999, "page_size": 1})
    manual = client.post(
        history_url, json={**payload, "client_request_id": str(uuid4())}
    )
    bulk = client.post(batch_url, json=batch)
    single = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    for rejected in (history, manual, bulk, single):
        assert rejected.status_code == 409, rejected.text
        assert "inconsistent action evidence" in rejected.text
        assert corrupt_value not in rejected.text

    pending = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert pending.status_code == 200, pending.text
    assert {item["review_state"] for item in pending.json()["items"]} == {"pending"}

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
        assert getattr(event, field) == corrupt_value
        setattr(event, field, original)
        session.commit()

    history = client.get(history_url)
    assert history.status_code == 200, history.text
    assert history.json()["requires_researcher_review"] is True
    replay = client.post(history_url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == event_id

    recovered = client.post(batch_url, json=batch)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["changed_count"] == len(item_ids)
    assert recovered.json()["requires_researcher_review"] is True
    replay_batch = client.post(batch_url, json=batch)
    assert replay_batch.status_code == 200, replay_batch.text
    assert replay_batch.json()["changed_count"] == 0


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_manual_and_bulk_apis_reject_new_nul_evidence(
    client: TestClient, saved_workflow: bool
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"

    manual_cases = [
        {"event_type": "comment", "actor": "human\x00hidden", "comment": "Inspect"},
        {"event_type": "comment", "actor": "human", "comment": "Inspect\x00hidden"},
        {"event_type": "assign", "actor": "human", "assignee": "reviewer\x00hidden"},
    ]
    for manual in manual_cases:
        invalid = client.post(url, json={**manual, "client_request_id": str(uuid4())})
        assert invalid.status_code == 422, invalid.text

    bulk_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    invalid_bulk = [
        {"item_ids": item_ids, "action": "start", "actor": "human\x00hidden"},
        {
            "item_ids": item_ids,
            "action": "skip",
            "actor": "human",
            "reason": "Unknown\x00effort",
        },
    ]
    for bulk in invalid_bulk:
        response = client.post(bulk_url, json=bulk)
        assert response.status_code == 422, response.text

    invalid_single = [
        (f"/api/v1/review-queue-items/{item_id}/start", {"actor": "human\x00hidden"}),
        (
            f"/api/v1/review-queue-items/{item_id}/skip",
            {"actor": "human", "reason": "Unknown\x00effort"},
        ),
    ]
    for path, payload in invalid_single:
        response = client.post(path, json=payload)
        assert response.status_code == 422, response.text

    history = client.get(url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 0
    assert history.json()["requires_researcher_review"] is True
    pending = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert pending.status_code == 200, pending.text
    assert {item["review_state"] for item in pending.json()["items"]} == {"pending"}
