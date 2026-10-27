"""Review queue coordination integration checks."""

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.tests.test_annotations import create_project, import_one


def test_comment_and_assignment_persist(client: TestClient) -> None:
    project = create_project(client, "Review coordination")
    import_one(client, project["id"])
    queue = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={}).json()
    item = client.get(f"/api/v1/review-queues/{queue['id']}/items").json()["items"][0]
    url = f"/api/v1/review-queues/{queue['id']}/items/{item['id']}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "comment",
        "actor": "researcher",
        "comment": "Inspect polyp edges",
    }
    response = client.post(url, json=payload)
    assert response.status_code == 201, response.text
    assert client.post(url, json=payload).json()["id"] == response.json()["id"]
    assert client.get(url).json()["total"] == 1

    assignment = client.post(
        url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "assign",
            "actor": "researcher",
            "assignee": "reviewer-two",
        },
    )
    assert assignment.status_code == 201, assignment.text
    assert client.get(url).json()["current_assignee"] == "reviewer-two"
    # Pagination changes only the visible events, never the queue-wide
    # assignment state or total. Empty pages must still retain both.
    second_page = client.get(url, params={"page": 2, "page_size": 1})
    assert second_page.status_code == 200, second_page.text
    assert second_page.json()["total"] == 2
    assert [event["event_type"] for event in second_page.json()["items"]] == ["assign"]
    assert second_page.json()["current_assignee"] == "reviewer-two"
    empty_page = client.get(url, params={"page": 3, "page_size": 1})
    assert empty_page.status_code == 200, empty_page.text
    assert empty_page.json()["total"] == 2
    assert empty_page.json()["items"] == []
    assert empty_page.json()["current_assignee"] == "reviewer-two"
    assert (
        client.post(
            url,
            json={
                "client_request_id": str(uuid4()),
                "event_type": "unassign",
                "actor": "researcher",
            },
        ).status_code
        == 201
    )
    assert client.get(url).json()["current_assignee"] is None


def test_single_item_triage_persists_atomic_events(client: TestClient) -> None:
    project = create_project(client, "Single item triage audit")
    import_one(client, project["id"])
    queue = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={}).json()
    item = client.get(f"/api/v1/review-queues/{queue['id']}/items").json()["items"][0]
    item_id = item["id"]
    history_url = f"/api/v1/review-queues/{queue['id']}/items/{item_id}/events"
    state_url = f"/api/v1/review-queue-items/{item_id}"

    started = client.post(f"{state_url}/start")
    assert started.status_code == 200, started.text
    assert started.json()["review_state"] == "in_progress"
    assert client.post(f"{state_url}/start").status_code == 409
    assert client.get(history_url).json()["total"] == 1

    invalid_skip = client.post(f"{state_url}/skip", json={"reason": ""})
    assert invalid_skip.status_code == 422, invalid_skip.text
    assert client.get(history_url).json()["total"] == 1

    skipped = client.post(f"{state_url}/skip", json={"reason": "Review polyp boundary"})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["review_state"] == "skipped"
    repeated_skip = client.post(f"{state_url}/skip", json={"reason": "Review polyp boundary"})
    assert repeated_skip.status_code == 409

    returned = client.post(f"{state_url}/return")
    assert returned.status_code == 200, returned.text
    assert returned.json()["review_state"] == "pending"
    assert client.post(f"{state_url}/return").status_code == 409

    history = client.get(history_url)
    assert history.status_code == 200, history.text
    assert history.json()["requires_researcher_review"] is True
    assert history.json()["total"] == 3
    assert [event["event_type"] for event in history.json()["items"]] == [
        "triage_start",
        "triage_skip",
        "triage_return",
    ]
    assert [event["actor"] for event in history.json()["items"]] == ["local_user"] * 3
    assert [event["comment"] for event in history.json()["items"]] == [
        None,
        "Review polyp boundary",
        None,
    ]
    assert len({event["client_request_id"] for event in history.json()["items"]}) == 3
    assert history.json()["current_assignee"] is None

    completed = client.post(f"{state_url}/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json()["review_state"] == "completed"
    assert completed.json()["completed_at"] is not None
    assert client.post(f"{state_url}/complete").status_code == 409
    assert client.post(f"{state_url}/start").status_code == 409
    final_history = client.get(history_url).json()
    assert final_history["total"] == 4
    assert [event["event_type"] for event in final_history["items"]] == [
        "triage_start",
        "triage_skip",
        "triage_return",
        "triage_complete",
    ]
    assert final_history["items"][-1]["actor"] == "local_user"
    assert final_history["items"][-1]["comment"] is None
    assert len({event["client_request_id"] for event in final_history["items"]}) == 4
    assert final_history["requires_researcher_review"] is True

    annotations = client.get(f"/api/v1/images/{item['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []


@pytest.mark.parametrize("tampered_field", ["project_id", "review_queue_id"])
def test_coordination_retries_and_history_reject_foreign_provenance(
    client: TestClient, tampered_field: str
) -> None:
    """A reused event key must not authenticate an event moved to another scope."""
    project = create_project(client, "Coordination provenance")
    import_one(client, project["id"])
    queue = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={})
    assert queue.status_code == 201, queue.text
    queue_id = queue.json()["id"]
    item = client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"][0]

    foreign_project = create_project(client, "Foreign coordination provenance")
    import_one(client, foreign_project["id"])
    foreign_queue = client.post(f"/api/v1/projects/{foreign_project['id']}/review-queues", json={})
    assert foreign_queue.status_code == 201, foreign_queue.text

    url = f"/api/v1/review-queues/{queue_id}/items/{item['id']}/events"
    payload = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": "researcher",
        "assignee": "reviewer-two",
    }
    created = client.post(url, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        original_scope = getattr(event, tampered_field)
        foreign_scope = (
            foreign_project["id"] if tampered_field == "project_id" else foreign_queue.json()["id"]
        )
        setattr(event, tampered_field, foreign_scope)
        session.commit()

    retry = client.post(url, json=payload)
    assert retry.status_code == 409, retry.text
    history = client.get(url)
    assert history.status_code == 409, history.text
    # A different request key must not append fresh reviewer evidence to a
    # queue whose existing coordination history has inconsistent provenance.
    fresh_payload = {
        "client_request_id": str(uuid4()),
        "event_type": "comment",
        "actor": "researcher",
        "comment": "New independent review note",
    }
    blocked_fresh = client.post(url, json=fresh_payload)
    assert blocked_fresh.status_code == 409, blocked_fresh.text
    # The corruption guard must run before pagination, including empty pages.
    assert client.get(url, params={"page": 2, "page_size": 1}).status_code == 409
    # A failed fresh write must not append an event, even though its request
    # identifier differs from the corrupted event's idempotency key.
    with app.state.session_factory() as session:
        event_count = (
            session.query(ReviewQueueItemEvent).filter_by(review_queue_item_id=item["id"]).count()
        )
        assert event_count == 1

    with app.state.session_factory() as session:
        event = session.get(ReviewQueueItemEvent, event_id)
        assert event is not None
        assert getattr(event, tampered_field) == foreign_scope
        assert event.actor == "researcher"
        assert event.assignee == "reviewer-two"
        setattr(event, tampered_field, original_scope)
        session.commit()

    recovered = client.post(url, json=payload)
    assert recovered.status_code == 201, recovered.text
    assert recovered.json()["id"] == event_id
    restored_history = client.get(url)
    assert restored_history.status_code == 200, restored_history.text
    assert restored_history.json()["total"] == 1
    assert restored_history.json()["current_assignee"] == "reviewer-two"
    # A previously blocked new key can now be committed exactly once.
    fresh = client.post(url, json=fresh_payload)
    assert fresh.status_code == 201, fresh.text
    assert client.post(url, json=fresh_payload).json()["id"] == fresh.json()["id"]
    final_history = client.get(url).json()
    assert final_history["total"] == 2
    assert [event["event_type"] for event in final_history["items"]] == ["assign", "comment"]
    assert final_history["requires_researcher_review"] is True
    assert final_history["current_assignee"] == "reviewer-two"
    annotations = client.get(f"/api/v1/images/{item['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []
