"""A committed QC batch must retain its real review-queue parent on disk."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from reefvision.db.models.review_queue_bulk_request import ReviewQueueBulkRequestRecord
from reefvision.tests.test_review_queue_bulk_16 import _queue_with_two_images


def _delete_review_queue(engine: Engine, queue_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM review_queues WHERE id = :queue_id"),
            {"queue_id": queue_id},
        )


def test_committed_bulk_request_restricts_queue_deletion_and_remains_retryable(
    client: TestClient,
) -> None:
    """A direct SQL delete must not orphan a committed researcher's QC audit."""
    queue_id, item_ids = _queue_with_two_images(client)
    request_id = str(uuid4())
    bulk_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    payload = {
        "item_ids": item_ids,
        "action": "start",
        "actor": "researcher one",
        "client_request_id": request_id,
    }
    response = client.post(bulk_url, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["changed_count"] == 2

    app = cast(FastAPI, client.app)
    with app.state.engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        links = connection.execute(
            text("PRAGMA foreign_key_list(review_queue_bulk_requests)")
        ).all()
    assert any(row[2] == "review_queues" and row[6] == "RESTRICT" for row in links)

    event_urls = [
        f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
        for item_id in item_ids
    ]
    before = [client.get(url).json() for url in event_urls]
    assert all(history["total"] == 1 for history in before)

    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        _delete_review_queue(app.state.engine, queue_id)

    with app.state.session_factory() as session:
        record = session.get(ReviewQueueBulkRequestRecord, request_id)
        assert record is not None
        assert record.review_queue_id == queue_id
        assert record.item_ids_json == sorted(item_ids)

    retry = client.post(bulk_url, json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()["changed_count"] == 0
    assert retry.json()["requires_researcher_review"] is True
    assert [client.get(url).json() for url in event_urls] == before
