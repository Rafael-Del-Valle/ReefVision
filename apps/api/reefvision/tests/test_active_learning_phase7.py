from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def test_active_learning_round_freezes_selection_and_feedback(client: TestClient) -> None:
    project = create_project(client, "Active learning study")
    first = import_one(
        client,
        project["id"],
        filename="first.png",
        relative_path="round/first.png",
    )
    second = import_one(
        client,
        project["id"],
        filename="second.png",
        relative_path="round/second.png",
    )
    assert first["successful"] and second["successful"]

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Round 1",
            "strategy": "uncertainty",
            "requested_size": 1,
        },
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    assert round_record["selected_count"] == 1
    assert round_record["strategy"] == "uncertainty"
    assert len(round_record["selection_manifest_json"]["items"]) == 1
    assert len(round_record["selection_sha256"]) == 64

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Equivalent round",
            "strategy": "uncertainty",
            "requested_size": 1,
        },
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == round_record["id"]

    item_id = round_record["selection_manifest_json"]["items"][0]["queue_item_id"]
    completed = client.post(f"/api/v1/review-queue-items/{item_id}/complete")
    assert completed.status_code == 200, completed.text

    feedback = client.get(
        f"/api/v1/active-learning-rounds/{round_record['id']}/feedback"
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["completed_count"] == 1
    assert feedback.json()["completion_fraction"] == 1.0

    finalized = client.post(
        f"/api/v1/active-learning-rounds/{round_record['id']}/complete"
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "complete"


def test_active_learning_rejects_foreign_models(client: TestClient) -> None:
    project = create_project(client, "Active learning scope")
    import_one(client, project["id"], filename="sample.png", relative_path="sample.png")

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Bad model scope",
            "strategy": "hybrid",
            "requested_size": 1,
            "model_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert response.status_code == 422
