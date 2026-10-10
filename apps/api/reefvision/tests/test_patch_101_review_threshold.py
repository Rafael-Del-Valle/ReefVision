"""Patch 1.0.1 confidence gating must never silently verify predictions."""

from fastapi.testclient import TestClient
from pydantic import ValidationError

from reefvision.schemas.review_queues import ReviewQueueCreateRequest
from reefvision.tests.test_annotations import create_project, import_one


def test_review_threshold_validation() -> None:
    assert ReviewQueueCreateRequest(review_below_confidence=0.5).review_below_confidence == 0.5
    for threshold in (-0.1, 1.1):
        try:
            ReviewQueueCreateRequest(review_below_confidence=threshold)
        except ValidationError:
            continue
        raise AssertionError(f"Invalid reviewer confidence cutoff accepted: {threshold}")


def test_low_confidence_queue_excludes_images_without_pending_model_proposals(
    client: TestClient,
) -> None:
    project = create_project(client, "Confidence threshold study")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]

    gated = client.post(
        f"/api/v1/projects/{project['id']}/review-queues",
        json={"review_below_confidence": 0.5},
    )
    assert gated.status_code == 201, gated.text
    queue = gated.json()
    assert queue["configuration_json"]["review_below_confidence"] == 0.5
    assert queue["item_count"] == 0

    ungated = client.post(f"/api/v1/projects/{project['id']}/review-queues", json={})
    assert ungated.status_code == 201, ungated.text
    ungated_items = client.get(f"/api/v1/review-queues/{ungated.json()['id']}/items")
    assert ungated_items.status_code == 200
    assert [item["image_id"] for item in ungated_items.json()["items"]] == [image_id]

    regenerated = client.post(f"/api/v1/review-queues/{queue['id']}/regenerate")
    assert regenerated.status_code == 201, regenerated.text
    assert regenerated.json()["configuration_json"]["review_below_confidence"] == 0.5
    assert regenerated.json()["item_count"] == 0
