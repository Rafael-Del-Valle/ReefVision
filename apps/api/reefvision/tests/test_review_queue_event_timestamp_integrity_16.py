"""Malformed restored QC event timestamps must fail closed before ORM decoding.

Runs against disposable SQLite for both standalone and *persisted executable*
Workflow Builder queues; never attempts to repair a researcher's audit history.
"""

from __future__ import annotations

import warnings
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SADeprecationWarning

from reefvision.tests.test_review_queue_bulk_sqlite_contention_16 import _make_queue


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "not-a-timestamp",
        "0000-01-01 12:00:00.000000",
        "2026-02-30 12:00:00.000000",
        "2026-11-17 24:00:00.000000",
        "2026-11-17 12:00:00.000000\x00hidden",
    ],
)
def test_imported_invalid_event_time_blocks_audit_and_recovers_only_after_fixture_restore(
    client: TestClient, saved_workflow: bool, bad_timestamp: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    events_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "local coral researcher",
        "assignee": "second researcher",
    }
    created = client.post(events_url, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        original_timestamp = session.execute(
            text("SELECT created_at FROM review_queue_item_events WHERE id = :id"),
            {"id": event_id},
        ).scalar_one()
        session.execute(
            text("UPDATE review_queue_item_events SET created_at = :value WHERE id = :id"),
            {"id": event_id, "value": bad_timestamp},
        )
        session.commit()

    # Even an off-page event must block replays and new coordination actions.
    # SQLAlchemy's DateTime result processor must never deserialize this row.
    requests = [
        client.get(events_url, params={"page": 999, "page_size": 1}),
        client.post(events_url, json=payload),
        client.post(
            events_url,
            json={
                "client_request_id": str(uuid4()),
                "event_type": "comment",
                "actor": "local coral researcher",
                "comment": "Check the branch margin before accepting",
            },
        ),
        client.post(f"/api/v1/review-queue-items/{item_id}/start"),
        client.post(
            f"/api/v1/review-queues/{queue_id}/items/bulk",
            json={
                "item_ids": item_ids,
                "action": "start",
                "actor": "local coral researcher",
                "client_request_id": str(uuid4()),
            },
        ),
    ]
    for response in requests:
        assert response.status_code == 409, response.text
        assert "inconsistent action evidence" in response.text
        assert bad_timestamp not in response.text

    listing = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert listing.status_code == 200, listing.text
    assert {item["review_state"] for item in listing.json()["items"]} == {"pending"}
    with app.state.session_factory() as session:
        assert (
            session.execute(
                text(
                    "SELECT COUNT(*) FROM review_queue_item_events WHERE review_queue_item_id = :id"
                ),
                {"id": item_id},
            ).scalar_one()
            == 1
        )
        assert (
            session.execute(
                text("SELECT created_at FROM review_queue_item_events WHERE id = :id"),
                {"id": event_id},
            ).scalar_one()
            == bad_timestamp
        )
        # Restore only the disposable fixture; production never auto-repairs.
        session.execute(
            text("UPDATE review_queue_item_events SET created_at = :value WHERE id = :id"),
            {"id": event_id, "value": original_timestamp},
        )
        session.commit()

    recovered = client.get(events_url)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["total"] == 1
    assert recovered.json()["current_assignee"] == "second researcher"
    assert recovered.json()["requires_researcher_review"] is True
    replay = client.post(events_url, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == event_id

@pytest.mark.parametrize("saved_workflow", [False, True])
def test_valid_review_timestamp_guard_has_no_sqlalchemy_deprecation(
    client: TestClient, saved_workflow: bool
) -> None:
    """Live and saved QC workflows must still accept canonical action history."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    url = f"/api/v1/review-queues/{queue_id}/items/{item_ids[0]}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "local coral reviewer",
        "assignee": "second researcher",
    }
    # This caught the CI-wide regression when a String GLOB expression was
    # inverted with ~; warnings-as-errors must hold even outside CI settings.
    with warnings.catch_warnings():
        warnings.simplefilter("error", SADeprecationWarning)
        created = client.post(url, json=payload)
        history = client.get(url)
        replay = client.post(url, json=payload)

    assert created.status_code == 201, created.text
    assert history.status_code == 200, history.text
    assert replay.status_code == 201, replay.text
    assert history.json()["total"] == 1
    assert history.json()["requires_researcher_review"] is True
    assert replay.json()["id"] == created.json()["id"]
