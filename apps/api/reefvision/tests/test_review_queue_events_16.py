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
