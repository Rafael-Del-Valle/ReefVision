"""QC audit actions must not silently survive inconsistent imported event fields.

Test standalone and saved executable Workflow Builder queues using disposable
SQLite records, without approving or rewriting scientific annotations.
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
    ("field", "invalid_value"),
    [
        ("event_type", "unassign"),
        ("event_type", "triage_start"),
        ("assignee", None),
        ("assignee", "  "),
        ("comment", "unapproved extra note"),
    ],
)
def test_inconsistent_reviewer_action_blocks_history_and_new_audit_writes(
    client: TestClient, saved_workflow: bool, field: str, invalid_value: str | None
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    original_payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "local researcher",
        "assignee": "reviewer-one",
    }
    created = client.post(url, json=original_payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        original_value = getattr(event, field)
        setattr(event, field, invalid_value)
        session.commit()

    # Even an out-of-window corrupt record blocks all history pages.
    for page in (1, 1000):
        rejected = client.get(url, params={"page": page, "page_size": 1})
        assert rejected.status_code == 409, rejected.text
        assert "inconsistent action evidence" in rejected.text
        assert "reviewer-one" not in rejected.text

    rejected_write = client.post(url, json={**original_payload, "client_request_id": str(uuid4())})
    assert rejected_write.status_code == 409, rejected_write.text
    assert "inconsistent action evidence" in rejected_write.text

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
        assert getattr(event, field) == invalid_value
        setattr(event, field, original_value)
        session.commit()

    restored = client.get(url)
    assert restored.status_code == 200, restored.text
    assert restored.json()["total"] == 1
    assert restored.json()["current_assignee"] == "reviewer-one"
    assert restored.json()["requires_researcher_review"] is True
    assert restored.json()["items"][0]["id"] == event_id

    review_items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert review_items.status_code == 200, review_items.text
    assert (
        next(item["review_state"] for item in review_items.json()["items"] if item["id"] == item_id)
        == "pending"
    )


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize("blank_comment", ["  ", "\t \r\n"])
def test_tampered_comment_without_text_fails_closed(
    client: TestClient, saved_workflow: bool, blank_comment: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    created = client.post(
        url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "researcher",
            "comment": "Inspect coral branch tip",
        },
    )
    assert created.status_code == 201, created.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, created.json()["id"])
        assert event is not None
        event.comment = blank_comment
        session.commit()
    rejected = client.get(url)
    assert rejected.status_code == 409, rejected.text
    assert "inconsistent action evidence" in rejected.text


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize("keyed", [False, True])
def test_bulk_triage_cannot_bypass_malformed_manual_event(
    client: TestClient, saved_workflow: bool, keyed: bool
) -> None:
    """An invalid action in one selected item blocks the entire batch."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_url = f"/api/v1/review-queues/{queue_id}/items/{item_ids[0]}/events"
    batch_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    created = client.post(
        item_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "assign",
            "actor": "local researcher",
            "assignee": "private reviewer",
        },
    )
    assert created.status_code == 201, created.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, created.json()["id"])
        assert event is not None
        event.assignee = None
        session.commit()

    payload = {"item_ids": item_ids, "action": "start", "actor": "local researcher"}
    if keyed:
        payload["client_request_id"] = str(uuid4())
    rejected = client.post(batch_url, json=payload)
    assert rejected.status_code == 409, rejected.text
    assert "inconsistent action evidence" in rejected.text
    assert "private reviewer" not in rejected.text
    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    assert {item["review_state"] for item in items.json()["items"]} == {"pending"}
    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent).where(
                    ReviewQueueItemEvent.review_queue_item_id.in_(item_ids)
                )
            )
        )
        assert len(events) == 1
        if keyed:
            from reefvision.db.models.review_queue_bulk_request import ReviewQueueBulkRequestRecord

            assert session.get(ReviewQueueBulkRequestRecord, payload["client_request_id"]) is None
        event = session.get(ReviewQueueItemEvent, created.json()["id"])
        assert event is not None
        event.assignee = "private reviewer"
        session.commit()

    retried = client.post(batch_url, json=payload)
    assert retried.status_code == 200, retried.text
    assert retried.json()["changed_count"] == len(item_ids)
    assert retried.json()["requires_researcher_review"] is True
    assert {item["review_state"] for item in retried.json()["items"]} == {"in_progress"}


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_bulk_idempotent_replay_cannot_accept_malformed_prior_triage(
    client: TestClient, saved_workflow: bool
) -> None:
    """An already-registered bulk UUID must not mask malformed event evidence."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    batch_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    payload = {
        "item_ids": [item_ids[0]],
        "action": "start",
        "actor": "local researcher",
        "client_request_id": str(uuid4()),
    }
    first = client.post(batch_url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 1
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.scalar(
            select(ReviewQueueItemEvent).where(
                ReviewQueueItemEvent.review_queue_item_id == item_ids[0]
            )
        )
        assert event is not None
        assert event.event_type == "triage_start"
        event.assignee = "forged assignee"
        session.commit()

    rejected = client.post(batch_url, json=payload)
    assert rejected.status_code == 409, rejected.text
    assert "inconsistent action evidence" in rejected.text
    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent).where(
                    ReviewQueueItemEvent.review_queue_item_id == item_ids[0]
                )
            )
        )
        assert len(events) == 1
        assert events[0].assignee == "forged assignee"
        events[0].assignee = None
        session.commit()

    replay = client.post(batch_url, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["changed_count"] == 0
    assert replay.json()["requires_researcher_review"] is True


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize(
    ("action", "field", "bad_value"),
    [
        ("start", "comment", "forged audit note"),
        ("skip", "comment", None),
        ("skip", "comment", " \t\r\n"),
        ("return", "comment", "forged audit note"),
        ("complete", "comment", "forged audit note"),
        ("start", "actor", "  "),
    ],
)
def test_corrupt_bulk_reason_or_actor_blocks_history_and_keyed_replay(
    client: TestClient,
    saved_workflow: bool,
    action: str,
    field: str,
    bad_value: str | None,
) -> None:
    """Stand-alone and saved, executed QC graphs share typed action evidence."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    bulk_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    history_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    if action == "complete":
        prepared = client.post(
            bulk_url, json={"item_ids": [item_id], "action": "start", "actor": "researcher"}
        )
        assert prepared.status_code == 200, prepared.text
    elif action == "return":
        prepared = client.post(
            bulk_url,
            json={
                "item_ids": [item_id],
                "action": "skip",
                "reason": "Unclear substrate",
                "actor": "researcher",
            },
        )
        assert prepared.status_code == 200, prepared.text
    payload = {
        "item_ids": [item_id],
        "action": action,
        "actor": "researcher",
        "client_request_id": str(uuid4()),
    }
    if action == "skip":
        payload["reason"] = "Outside observation effort"
    elif action == "complete":
        payload["review_confirmed"] = True
    initial = client.post(bulk_url, json=payload)
    assert initial.status_code == 200, initial.text
    assert initial.json()["changed_count"] == 1
    original_state = initial.json()["items"][0]["review_state"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.scalar(
            select(ReviewQueueItemEvent).where(
                ReviewQueueItemEvent.review_queue_item_id == item_id,
                ReviewQueueItemEvent.event_type == f"triage_{action}",
            )
        )
        assert event is not None
        event_id = event.id
        original_value = getattr(event, field)
        setattr(event, field, bad_value)
        session.commit()

    history = client.get(history_url, params={"page": 1000, "page_size": 1})
    assert history.status_code == 409, history.text
    assert "inconsistent action evidence" in history.text
    replay = client.post(bulk_url, json=payload)
    assert replay.status_code == 409, replay.text
    assert "inconsistent action evidence" in replay.text
    assert "Outside observation effort" not in replay.text
    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    assert (
        next(item["review_state"] for item in items.json()["items"] if item["id"] == item_id)
        == original_state
    )
    with app.state.session_factory() as session:
        matching = list(
            session.scalars(
                select(ReviewQueueItemEvent.id).where(
                    ReviewQueueItemEvent.review_queue_item_id == item_id,
                    ReviewQueueItemEvent.event_type == f"triage_{action}",
                )
            )
        )
        assert matching == [event_id]
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        assert getattr(event, field) == bad_value
        # Restore only a disposable test fixture, never historical user records.
        setattr(event, field, original_value)
        session.commit()
    restored = client.post(bulk_url, json=payload)
    assert restored.status_code == 200, restored.text
    assert restored.json()["changed_count"] == 0
    assert restored.json()["requires_researcher_review"] is True


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize(
    ("event_type", "field", "blank_value"),
    [
        ("comment", "actor", "\u00a0\u2003"),
        ("comment", "comment", "\u202f\u3000"),
        ("assign", "assignee", "\u2007\u205f"),
    ],
)
def test_unicode_whitespace_only_history_blocks_all_coordination_paths(
    client: TestClient,
    saved_workflow: bool,
    event_type: str,
    field: str,
    blank_value: str,
) -> None:
    """Imported Unicode blanks must be rejected like incoming .strip() blanks."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    history_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": event_type,
        "actor": "local researcher",
    }
    if event_type == "comment":
        payload["comment"] = "Uncertain coral polyp"
    else:
        payload["assignee"] = "private reviewer"
    created = client.post(history_url, json=payload)
    assert created.status_code == 201, created.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, created.json()["id"])
        assert event is not None
        original = getattr(event, field)
        setattr(event, field, blank_value)
        session.commit()

    # The corrupted event may be outside the requested history page.
    history = client.get(history_url, params={"page": 1000, "page_size": 1})
    manual = client.post(history_url, json={**payload, "client_request_id": str(uuid4())})
    bulk = client.post(
        f"/api/v1/review-queues/{queue_id}/items/bulk",
        json={"item_ids": item_ids, "action": "start", "actor": "researcher"},
    )
    single = client.post(f"/api/v1/review-queue-items/{item_id}/start")
    for response in (history, manual, bulk, single):
        assert response.status_code == 409, response.text
        assert "inconsistent action evidence" in response.text
        assert "private reviewer" not in response.text

    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent).where(
                    ReviewQueueItemEvent.review_queue_item_id == item_id
                )
            )
        )
        assert len(events) == 1
        assert getattr(events[0], field) == blank_value
        setattr(events[0], field, original)
        session.commit()

    restored = client.get(history_url)
    assert restored.status_code == 200, restored.text
    assert restored.json()["requires_researcher_review"] is True
    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    assert (
        next(item["review_state"] for item in items.json()["items"] if item["id"] == item_id)
        == "pending"
    )


@pytest.mark.parametrize("saved_workflow", [False, True])
def test_unicode_blank_skip_reason_blocks_registered_bulk_retry(
    client: TestClient, saved_workflow: bool
) -> None:
    """An existing bulk request key cannot bless a Unicode-only skip reason."""
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    item_id = item_ids[0]
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    payload = {
        "item_ids": [item_id],
        "action": "skip",
        "actor": "researcher",
        "reason": "Turbid image; uncountable polyps",
        "client_request_id": str(uuid4()),
    }
    first = client.post(url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 1

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.scalar(
            select(ReviewQueueItemEvent).where(
                ReviewQueueItemEvent.review_queue_item_id == item_id,
                ReviewQueueItemEvent.event_type == "triage_skip",
            )
        )
        assert event is not None
        event.comment = "\u00a0\u3000"
        session.commit()

    history = client.get(f"/api/v1/review-queues/{queue_id}/items/{item_id}/events")
    replay = client.post(url, json=payload)
    single = client.post(f"/api/v1/review-queue-items/{item_id}/return")
    for response in (history, replay, single):
        assert response.status_code == 409, response.text
        assert "inconsistent action evidence" in response.text
        assert "Turbid image" not in response.text

    with app.state.session_factory() as session:
        event = session.scalar(
            select(ReviewQueueItemEvent).where(
                ReviewQueueItemEvent.review_queue_item_id == item_id,
                ReviewQueueItemEvent.event_type == "triage_skip",
            )
        )
        assert event is not None
        assert event.comment == "\u00a0\u3000"
        event.comment = payload["reason"]
        session.commit()

    retried = client.post(url, json=payload)
    assert retried.status_code == 200, retried.text
    assert retried.json()["changed_count"] == 0
    assert retried.json()["requires_researcher_review"] is True
