"""Bulk QC triage: atomic validation, retry safety and non-verification."""

from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def _queue_with_two_images(client: TestClient) -> tuple[str, list[str]]:
    project = create_project(client, "Bulk QC triage")
    import_one(
        client,
        project["id"],
        filename="frame-one.png",
        relative_path="bulk/frame-one.png",
        size=(80, 60),
    )
    import_one(
        client,
        project["id"],
        filename="frame-two.png",
        relative_path="bulk/frame-two.png",
        size=(81, 60),
    )
    created = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={})
    assert created.status_code == 201, created.text
    queue_id = created.json()["id"]
    response = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["items"]]
    assert len(ids) == 2
    return queue_id, ids


def test_bulk_review_triage_is_idempotent_and_does_not_verify_annotations(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    skipped = client.post(
        url, json={"item_ids": ids, "action": "skip", "reason": "Manual inspection"}
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["changed_count"] == 2
    assert skipped.json()["requires_researcher_review"] is True
    assert {item["review_state"] for item in skipped.json()["items"]} == {"skipped"}

    replay = client.post(
        url, json={"item_ids": ids, "action": "skip", "reason": "Manual inspection"}
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["changed_count"] == 0

    returned = client.post(url, json={"item_ids": ids, "action": "return"})
    assert returned.status_code == 200, returned.text
    assert returned.json()["changed_count"] == 2
    assert client.post(url, json={"item_ids": ids, "action": "return"}).json()["changed_count"] == 0

    started = client.post(url, json={"item_ids": ids, "action": "start"})
    assert started.status_code == 200, started.text
    assert started.json()["changed_count"] == 2
    assert client.post(url, json={"item_ids": ids, "action": "start"}).json()["changed_count"] == 0
    assert {item["review_state"] for item in started.json()["items"]} == {"in_progress"}
    for item in started.json()["items"]:
        session = client.get(f"/api/v1/images/{item['image_id']}/annotations")
        assert session.status_code == 200
        assert session.json()["annotations"] == []


def test_bulk_review_rejects_partial_changes_and_foreign_queue_members(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    assert (
        client.post(
            url, json={"item_ids": [ids[1]], "action": "skip", "reason": "Hold"}
        ).status_code
        == 200
    )

    # First item is valid, second cannot be started; neither may be changed.
    invalid = client.post(url, json={"item_ids": ids, "action": "start"})
    assert invalid.status_code == 409, invalid.text
    listing = client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"]
    states = {item["id"]: item["review_state"] for item in listing}
    assert states[ids[0]] == "pending"
    assert states[ids[1]] == "skipped"

    duplicate = client.post(url, json={"item_ids": [ids[0], ids[0]], "action": "start"})
    assert duplicate.status_code != 200
    missing_reason = client.post(url, json={"item_ids": ids, "action": "skip"})
    assert missing_reason.status_code != 200

    another_queue_id, other_ids = _queue_with_two_images(client)
    assert another_queue_id != queue_id
    foreign = client.post(url, json={"item_ids": [ids[0], other_ids[0]], "action": "start"})
    assert foreign.status_code == 409, foreign.text
    assert client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"][0][
        "review_state"
    ] in {"pending", "skipped"}

    # Rejected mixed-state and foreign-queue batches must not leave orphan audit events.
    first_history = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events")
    second_history = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events")
    assert first_history.status_code == 200, first_history.text
    assert second_history.status_code == 200, second_history.text
    assert first_history.json()["total"] == 0
    assert [event["event_type"] for event in second_history.json()["items"]] == ["triage_skip"]


def test_bulk_triage_appends_atomic_actor_labeled_events(client: TestClient) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    event_urls = [f"/api/v1/review-queues/{queue_id}/items/{item_id}/events" for item_id in ids]
    payload = {
        "item_ids": ids,
        "action": "skip",
        "reason": "Unclear polyp boundary",
        "actor": "  lab reviewer  ",
    }
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["changed_count"] == 2
    for event_url in event_urls:
        history = client.get(event_url)
        assert history.status_code == 200, history.text
        assert history.json()["total"] == 1
        event = history.json()["items"][0]
        assert event["event_type"] == "triage_skip"
        assert event["actor"] == "lab reviewer"
        assert event["comment"] == "Unclear polyp boundary"
        assert history.json()["current_assignee"] is None

    assert client.post(url, json=payload).json()["changed_count"] == 0
    assert all(client.get(event_url).json()["total"] == 1 for event_url in event_urls)

    invalid = client.post(url, json={"item_ids": ids, "action": "return", "actor": "   "})
    assert invalid.status_code == 422, invalid.text
    # Public coordination API must not permit a forged triage audit event.
    forged = client.post(
        event_urls[0],
        json={
            "client_request_id": "1c3b1e54-6e94-4ac2-ae90-25fdc52bd1c1",
            "event_type": "triage_return",
            "actor": "forged reviewer",
        },
    )
    assert forged.status_code == 422, forged.text
    assert all(client.get(event_url).json()["total"] == 1 for event_url in event_urls)

    returned = client.post(url, json={"item_ids": ids, "action": "return", "actor": "lab reviewer"})
    assert returned.status_code == 200, returned.text
    assert returned.json()["changed_count"] == 2
    for event_url in event_urls:
        history = client.get(event_url).json()
        assert history["total"] == 2
        assert [entry["event_type"] for entry in history["items"]] == [
            "triage_skip",
            "triage_return",
        ]
        assert history["items"][1]["comment"] is None

    started = client.post(url, json={"item_ids": ids, "action": "start", "actor": "lab reviewer"})
    assert started.status_code == 200, started.text
    assert started.json()["changed_count"] == 2
    assert (
        client.post(url, json={"item_ids": ids, "action": "start", "actor": "lab reviewer"}).json()[
            "changed_count"
        ]
        == 0
    )
    for event_url in event_urls:
        history = client.get(event_url).json()
        assert history["total"] == 3
        assert history["items"][2]["event_type"] == "triage_start"
        assert history["current_assignee"] is None



def test_bulk_completion_requires_manual_confirmation_and_preserves_annotations(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    complete = {
        "item_ids": ids,
        "action": "complete",
        "actor": "self-reported reviewer",
        "review_confirmed": True,
    }
    assert client.post(url, json=complete).status_code == 409
    assert client.post(url, json={**complete, "review_confirmed": False}).status_code == 422
    assert client.post(url, json={**complete, "review_confirmed": "yes"}).status_code == 422
    assert (
        client.post(
            url, json={"item_ids": ids, "action": "start", "review_confirmed": True}
        ).status_code
        == 422
    )
    started = client.post(url, json={"item_ids": ids, "action": "start"})
    assert started.status_code == 200, started.text
    result = client.post(url, json=complete)
    assert result.status_code == 200, result.text
    assert result.json()["changed_count"] == 2
    assert result.json()["requires_researcher_review"] is True
    for item in result.json()["items"]:
        assert item["review_state"] == "completed"
        assert item["started_at"] is not None
        assert item["completed_at"] is not None
        history = client.get(f"/api/v1/review-queues/{queue_id}/items/{item['id']}/events").json()
        assert [event["event_type"] for event in history["items"]] == [
            "triage_start",
            "triage_complete",
        ]
        assert history["items"][-1]["actor"] == "self-reported reviewer"
        assert history["requires_researcher_review"] is True
        annotations = client.get(f"/api/v1/images/{item['image_id']}/annotations")
        assert annotations.status_code == 200
        assert annotations.json()["annotations"] == []
    retry = client.post(url, json=complete)
    assert retry.status_code == 200, retry.text
    assert retry.json()["changed_count"] == 0
    for item_id in ids:
        assert (
            client.get(f"/api/v1/review-queues/{queue_id}/items/{item_id}/events").json()["total"]
            == 2
        )


def test_bulk_completion_rejects_mixed_states_atomically(client: TestClient) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    assert client.post(url, json={"item_ids": [ids[0]], "action": "start"}).status_code == 200
    rejected = client.post(
        url,
        json={"item_ids": ids, "action": "complete", "review_confirmed": True},
    )
    assert rejected.status_code == 409, rejected.text
    listing = client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"]
    assert {item["id"]: item["review_state"] for item in listing} == {
        ids[0]: "in_progress",
        ids[1]: "pending",
    }
    assert (
        client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events").json()["total"] == 1
    )
