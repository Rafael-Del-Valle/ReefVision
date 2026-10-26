"""Bulk QC triage: atomic validation, retry safety and non-verification."""

from __future__ import annotations

from uuid import uuid4

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
    first_url = f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events"
    second_url = f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events"
    first_history = client.get(first_url)
    second_history = client.get(second_url)
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


def test_bulk_completion_partial_retry_preserves_original_reviewer_audit(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    started = client.post(url, json={"item_ids": ids, "action": "start"})
    assert started.status_code == 200, started.text

    first = client.post(
        url,
        json={
            "item_ids": [ids[0]],
            "action": "complete",
            "review_confirmed": True,
            "actor": "first reviewer",
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 1
    original_completion = first.json()["items"][0]["completed_at"]

    retry = client.post(
        url,
        json={
            "item_ids": ids,
            "action": "complete",
            "review_confirmed": True,
            "actor": "second reviewer",
        },
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["changed_count"] == 1
    assert {item["review_state"] for item in retry.json()["items"]} == {"completed"}
    assert retry.json()["items"][0]["completed_at"] == original_completion

    first_events = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events")
    second_events = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events")
    assert first_events.status_code == 200, first_events.text
    assert second_events.status_code == 200, second_events.text
    assert [event["event_type"] for event in first_events.json()["items"]] == [
        "triage_start",
        "triage_complete",
    ]
    assert [event["event_type"] for event in second_events.json()["items"]] == [
        "triage_start",
        "triage_complete",
    ]
    assert first_events.json()["items"][-1]["actor"] == "first reviewer"
    assert second_events.json()["items"][-1]["actor"] == "second reviewer"
    assert first_events.json()["requires_researcher_review"] is True
    assert second_events.json()["requires_researcher_review"] is True

    again = client.post(
        url,
        json={"item_ids": ids, "action": "complete", "review_confirmed": True},
    )
    assert again.status_code == 200, again.text
    assert again.json()["changed_count"] == 0
    for item_id in ids:
        events = client.get(f"/api/v1/review-queues/{queue_id}/items/{item_id}/events")
        assert events.status_code == 200, events.text
        assert events.json()["total"] == 2


def test_bulk_completion_mixed_completed_and_pending_preserves_audit(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    bulk_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    first_event_url = f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events"
    second_event_url = f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events"

    started = client.post(bulk_url, json={"item_ids": [ids[0]], "action": "start"})
    assert started.status_code == 200, started.text
    completed = client.post(
        bulk_url,
        json={
            "item_ids": [ids[0]],
            "action": "complete",
            "review_confirmed": True,
            "actor": "original reviewer",
        },
    )
    assert completed.status_code == 200, completed.text
    original_completion = completed.json()["items"][0]["completed_at"]
    original_history = client.get(first_event_url).json()
    assert [event["event_type"] for event in original_history["items"]] == [
        "triage_start",
        "triage_complete",
    ]
    assert original_history["items"][-1]["actor"] == "original reviewer"

    rejected = client.post(
        bulk_url,
        json={
            "item_ids": ids,
            "action": "complete",
            "review_confirmed": True,
            "actor": "different reviewer",
        },
    )
    assert rejected.status_code == 409, rejected.text
    items = client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"]
    by_id = {item["id"]: item for item in items}
    assert by_id[ids[0]]["review_state"] == "completed"
    assert by_id[ids[0]]["completed_at"] == original_completion
    assert by_id[ids[1]]["review_state"] == "pending"
    assert client.get(first_event_url).json() == original_history
    assert client.get(second_event_url).json()["total"] == 0


def test_keyed_bulk_retry_never_reapplies_after_intervening_reviewer_action(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    request_id = str(uuid4())
    first = {
        "item_ids": ids,
        "action": "start",
        "actor": "researcher one",
        "client_request_id": request_id,
    }
    started = client.post(url, json=first)
    assert started.status_code == 200, started.text
    assert started.json()["changed_count"] == 2

    # A second researcher changes the first item after the first batch
    # committed, but before its original HTTP response was acknowledged.
    skipped = client.post(
        url,
        json={
            "item_ids": [ids[0]],
            "action": "skip",
            "reason": "Manual inspection needed",
            "actor": "researcher two",
        },
    )
    assert skipped.status_code == 200, skipped.text

    replay = client.post(url, json=first)
    assert replay.status_code == 200, replay.text
    assert replay.json()["changed_count"] == 0
    assert {item["id"]: item["review_state"] for item in replay.json()["items"]} == {
        ids[0]: "skipped",
        ids[1]: "in_progress",
    }
    first_history = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events").json()
    assert [event["event_type"] for event in first_history["items"]] == [
        "triage_start",
        "triage_skip",
    ]
    assert first_history["items"][0]["actor"] == "researcher one"
    assert first_history["items"][1]["actor"] == "researcher two"
    assert (
        client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events").json()["total"] == 1
    )

    # A request key is bound to its original action, reviewer and reason.
    for changed in (
        {**first, "actor": "different reviewer"},
        {**first, "action": "skip", "reason": "different action"},
    ):
        rejected = client.post(url, json=changed)
        assert rejected.status_code == 409, rejected.text
    assert (
        client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events").json()
        == first_history
    )


def test_keyed_bulk_first_attempt_requires_all_items_to_transition(
    client: TestClient,
) -> None:
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    assert client.post(url, json={"item_ids": [ids[0]], "action": "start"}).status_code == 200
    rejected = client.post(
        url,
        json={
            "item_ids": ids,
            "action": "start",
            "client_request_id": str(uuid4()),
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert (
        client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events").json()["total"] == 0
    )
    assert (
        client.post(
            url,
            json={
                "item_ids": [ids[1]],
                "action": "start",
                "client_request_id": "not-a-uuid",
            },
        ).status_code
        == 422
    )


def test_keyed_bulk_skip_retry_preserves_later_return_and_reason_history(
    client: TestClient,
) -> None:
    """A lost skip response cannot undo a later researcher's return decision."""
    queue_id, ids = _queue_with_two_images(client)
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    original = {
        "item_ids": ids,
        "action": "skip",
        "reason": "Requires visual inspection",
        "actor": "researcher one",
        "client_request_id": str(uuid4()),
    }
    first = client.post(url, json=original)
    assert first.status_code == 200, first.text
    assert first.json()["changed_count"] == 2

    returned = client.post(
        url,
        json={"item_ids": [ids[0]], "action": "return", "actor": "researcher two"},
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["changed_count"] == 1

    replay = client.post(url, json=original)
    assert replay.status_code == 200, replay.text
    assert replay.json()["changed_count"] == 0
    assert {item["id"]: item["review_state"] for item in replay.json()["items"]} == {
        ids[0]: "pending",
        ids[1]: "skipped",
    }
    first_history = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events")
    second_history = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events")
    assert first_history.status_code == 200, first_history.text
    assert second_history.status_code == 200, second_history.text
    assert [event["event_type"] for event in first_history.json()["items"]] == [
        "triage_skip",
        "triage_return",
    ]
    assert first_history.json()["items"][1]["actor"] == "researcher two"
    assert second_history.json()["total"] == 1
    assert second_history.json()["items"][0]["comment"] == "Requires visual inspection"

    conflicting = client.post(url, json={**original, "reason": "Different reason"})
    assert conflicting.status_code == 409, conflicting.text
    # A conflicting reuse of the same request key must be atomic: it cannot
    # mutate either reviewer's event history or the original skip reason.
    first_after = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[0]}/events")
    second_after = client.get(f"/api/v1/review-queues/{queue_id}/items/{ids[1]}/events")
    assert first_after.status_code == 200, first_after.text
    assert second_after.status_code == 200, second_after.text
    assert first_after.json() == first_history.json()
    assert second_after.json() == second_history.json()


def test_keyed_bulk_retry_preserves_intervening_comments_and_assignments(
    client: TestClient,
) -> None:
    """A lost batch response cannot erase later human coordination events."""
    queue_id, ids = _queue_with_two_images(client)
    bulk_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    event_urls = [f"/api/v1/review-queues/{queue_id}/items/{item_id}/events" for item_id in ids]
    original = {
        "item_ids": ids,
        "action": "start",
        "actor": "first researcher",
        "client_request_id": str(uuid4()),
    }
    started = client.post(bulk_url, json=original)
    assert started.status_code == 200, started.text
    assert started.json()["changed_count"] == 2

    comment = client.post(
        event_urls[0],
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "second researcher",
            "comment": "Check the ambiguous polyp boundary",
        },
    )
    assert comment.status_code == 201, comment.text
    assignment = client.post(
        event_urls[1],
        json={
            "client_request_id": str(uuid4()),
            "event_type": "assign",
            "actor": "second researcher",
            "assignee": "third researcher",
        },
    )
    assert assignment.status_code == 201, assignment.text

    before = [client.get(event_url).json() for event_url in event_urls]
    assert [event["event_type"] for event in before[0]["items"]] == [
        "triage_start",
        "comment",
    ]
    assert [event["event_type"] for event in before[1]["items"]] == [
        "triage_start",
        "assign",
    ]
    assert before[1]["current_assignee"] == "third researcher"

    replay = client.post(bulk_url, json=original)
    assert replay.status_code == 200, replay.text
    assert replay.json()["changed_count"] == 0
    assert [client.get(event_url).json() for event_url in event_urls] == before

    conflicting = client.post(bulk_url, json={**original, "actor": "different researcher"})
    assert conflicting.status_code == 409, conflicting.text
    assert [client.get(event_url).json() for event_url in event_urls] == before
    for item in replay.json()["items"]:
        annotations = client.get(f"/api/v1/images/{item['image_id']}/annotations")
        assert annotations.status_code == 200, annotations.text
        assert annotations.json()["annotations"] == []


def test_keyed_start_retry_cannot_reopen_completed_review(client: TestClient) -> None:
    """A late HTTP retry must preserve a different researcher's completion."""
    queue_id, ids = _queue_with_two_images(client)
    item_id = ids[0]
    bulk_url = f"/api/v1/review-queues/{queue_id}/items/bulk"
    event_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
    keyed_start = {
        "item_ids": [item_id],
        "action": "start",
        "actor": "first reviewer",
        "client_request_id": str(uuid4()),
    }
    started = client.post(bulk_url, json=keyed_start)
    assert started.status_code == 200, started.text
    assert started.json()["changed_count"] == 1

    completed = client.post(
        bulk_url,
        json={
            "item_ids": [item_id],
            "action": "complete",
            "actor": "second reviewer",
            "review_confirmed": True,
        },
    )
    assert completed.status_code == 200, completed.text
    completion_timestamp = completed.json()["items"][0]["completed_at"]
    original_history = client.get(event_url).json()
    assert [event["event_type"] for event in original_history["items"]] == [
        "triage_start",
        "triage_complete",
    ]
    assert original_history["items"][-1]["actor"] == "second reviewer"

    retry = client.post(bulk_url, json=keyed_start)
    assert retry.status_code == 200, retry.text
    assert retry.json()["changed_count"] == 0
    assert retry.json()["items"][0]["review_state"] == "completed"
    assert retry.json()["items"][0]["completed_at"] == completion_timestamp
    assert retry.json()["requires_researcher_review"] is True
    assert client.get(event_url).json() == original_history

    conflicting = client.post(bulk_url, json={**keyed_start, "actor": "third reviewer"})
    assert conflicting.status_code == 409, conflicting.text
    assert client.get(event_url).json() == original_history
    completed_image_id = completed.json()["items"][0]["image_id"]
    annotations = client.get(f"/api/v1/images/{completed_image_id}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []
