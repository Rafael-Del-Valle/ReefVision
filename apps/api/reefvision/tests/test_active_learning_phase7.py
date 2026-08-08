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


def test_random_baseline_is_seeded_explainable_and_reproducible(
    client: TestClient,
) -> None:
    project = create_project(client, "Active learning random control")
    for index in range(4):
        imported = import_one(
            client,
            project["id"],
            filename=f"random-{index}.png",
            relative_path=f"random/random-{index}.png",
        )
        assert imported["successful"]

    payload = {
        "name": "Random control",
        "strategy": "random",
        "requested_size": 2,
        "random_seed": 17,
    }
    first = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json=payload,
    )
    assert first.status_code == 201, first.text
    first_round = first.json()
    assert first_round["strategy"] == "random"
    assert first_round["selected_count"] == 2
    assert first_round["strategy_config_json"]["random_seed"] == 17
    assert first_round["selection_manifest_json"]["random_seed"] == 17
    assert all(
        item["reason_summary"]
        == "Random baseline selection using deterministic seed 17."
        for item in first_round["selection_manifest_json"]["items"]
    )

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={**payload, "name": "Same seeded control"},
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == first_round["id"]

    different_seed = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={**payload, "name": "Different control", "random_seed": 18},
    )
    assert different_seed.status_code == 201, different_seed.text
    assert different_seed.json()["id"] != first_round["id"]
    assert different_seed.json()["selection_sha256"] != first_round["selection_sha256"]


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
