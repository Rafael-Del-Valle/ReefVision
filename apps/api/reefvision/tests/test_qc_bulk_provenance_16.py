"""A keyed QC retry must not trust an audit event from a different project."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models.review_queue_bulk_request import ReviewQueueBulkRequestRecord
from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_review_queue_bulk_16 import _queue_with_two_images


@pytest.mark.parametrize("legacy_layout", [False, True])
def test_keyed_retry_rejects_foreign_project_audit_without_mutation(
    client: TestClient, legacy_layout: bool
) -> None:
    """Even a correctly keyed event cannot claim another project's provenance."""
    queue_id, item_ids = _queue_with_two_images(client)
    unrelated_project = create_project(client, "Unrelated QC provenance")
    request_id = str(uuid4())
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    payload = {
        "item_ids": item_ids,
        "action": "start",
        "actor": "researcher one",
        "client_request_id": request_id,
    }
    first = client.post(url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 2

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent).where(ReviewQueueItemEvent.review_queue_id == queue_id)
            )
        )
        assert len(events) == 2
        assert {event.review_queue_item_id for event in events} == set(item_ids)
        original_project_id = events[0].project_id
        assert original_project_id != unrelated_project["id"]
        if legacy_layout:
            # Pre-registry 1.6 batches stored UUIDv5 for every selected item.
            for event in events:
                event.client_request_id = str(uuid5(UUID(request_id), event.review_queue_item_id))
        events[0].project_id = unrelated_project["id"]
        session.commit()

    event_urls = [
        f"/api/v1/review-queues/{queue_id}/items/{item_id}/events" for item_id in item_ids
    ]
    original_history = [client.get(event_url).json() for event_url in event_urls]
    retry = client.post(url, json=payload)
    assert retry.status_code == 409, retry.text
    assert [client.get(event_url).json() for event_url in event_urls] == original_history
    assert all(history["total"] == 1 for history in original_history)

    with app.state.session_factory() as session:
        record = session.get(ReviewQueueBulkRequestRecord, request_id)
        assert record is not None
        assert record.project_id == original_project_id
        assert record.item_ids_json == sorted(item_ids)

    items = client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"]
    assert {item["review_state"] for item in items} == {"in_progress"}
    for item in items:
        annotations = client.get(f"/api/v1/images/{item['image_id']}/annotations")
        assert annotations.status_code == 200, annotations.text
        assert annotations.json()["annotations"] == []

    # An explicitly repaired local audit record must become retryable again.
    # The API never repairs or rewrites the record itself.
    with app.state.session_factory() as session:
        corrupted = session.scalar(
            select(ReviewQueueItemEvent).where(
                ReviewQueueItemEvent.review_queue_id == queue_id,
                ReviewQueueItemEvent.project_id == unrelated_project["id"],
            )
        )
        assert corrupted is not None
        corrupted.project_id = original_project_id
        session.commit()

    recovered = client.post(url, json=payload)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["changed_count"] == 0
    assert recovered.json()["requires_researcher_review"] is True
    assert all(client.get(event_url).json()["total"] == 1 for event_url in event_urls)


def test_keyed_retry_rejects_audit_event_reassigned_to_another_queue(
    client: TestClient,
) -> None:
    """An existing foreign queue must not become valid provenance for a retry."""
    queue_id, item_ids = _queue_with_two_images(client)
    other_queue_id, _ = _queue_with_two_images(client)
    request_id = str(uuid4())
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    payload = {
        "item_ids": item_ids,
        "action": "start",
        "actor": "researcher one",
        "client_request_id": request_id,
    }
    first = client.post(url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 2

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.scalar(
            select(ReviewQueueItemEvent).where(
                ReviewQueueItemEvent.review_queue_item_id == item_ids[0]
            )
        )
        assert event is not None
        event.review_queue_id = other_queue_id
        session.commit()

    rejected = client.post(url, json=payload)
    assert rejected.status_code == 409, rejected.text
    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewQueueItemEvent).where(
                    ReviewQueueItemEvent.review_queue_item_id.in_(item_ids)
                )
            )
        )
        assert len(events) == 2
        assert {event.review_queue_id for event in events} == {queue_id, other_queue_id}
        assert all(event.event_type == "triage_start" for event in events)
        assert all(event.actor == "researcher one" for event in events)
        event = next(event for event in events if event.review_queue_id == other_queue_id)
        event.review_queue_id = queue_id
        session.commit()

    recovered = client.post(url, json=payload)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["changed_count"] == 0
    assert recovered.json()["requires_researcher_review"] is True
    for item_id in item_ids:
        history = client.get(f"/api/v1/review-queues/{queue_id}/items/{item_id}/events")
        assert history.status_code == 200, history.text
        assert history.json()["total"] == 1
