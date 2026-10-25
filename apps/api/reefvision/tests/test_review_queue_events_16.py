"""Review queue coordination integration checks."""

from uuid import uuid4

from fastapi.testclient import TestClient

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
