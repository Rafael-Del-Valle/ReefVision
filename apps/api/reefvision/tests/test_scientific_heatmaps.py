"""Scientific heatmap API and spatial semantics regressions."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import (
    create_project,
    import_one,
)


def _url(project_id: str, image_id: str) -> str:
    return f"/api/v1/projects/{project_id}/images/{image_id}/scientific-heatmaps"


def test_empty_heatmap_is_zero_and_repeatable(
    client: TestClient,
) -> None:
    project = create_project(client, "Empty heatmaps")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]

    response = client.get(
        _url(project["id"], image_id),
        params={"columns": 4, "rows": 3},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert len(data["layers"]) == 3
    assert [layer["kind"] for layer in data["layers"]] == [
        "reviewed_boxes",
        "verified_masks",
        "pending_predictions",
    ]

    for layer in data["layers"]:
        assert layer["object_count"] == 0
        assert layer["max_cell_count"] == 0
        assert layer["counts"] == [[0] * 4 for _ in range(3)]
        assert layer["normalized"] == [[0.0] * 4 for _ in range(3)]

    assert len(data["source_sha256"]) == 64
    assert len(data["content_sha256"]) == 64
    assert (
        client.get(
            _url(project["id"], image_id),
            params={"columns": 4, "rows": 3},
        ).json()["content_sha256"]
        == data["content_sha256"]
    )


def test_reviewed_boxes_and_verified_masks_remain_separate(
    client: TestClient,
) -> None:
    project = create_project(client, "Coral heatmaps")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    label_id = project["label_classes"][0]["id"]

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "x_min": 2,
                    "y_min": 2,
                    "x_max": 12,
                    "y_max": 12,
                }
            ],
            "mask_annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 25, "y": 20},
                        {"x": 45, "y": 20},
                        {"x": 45, "y": 40},
                        {"x": 25, "y": 40},
                    ],
                },
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "status": "draft",
                    "points": [
                        {"x": 50, "y": 10},
                        {"x": 60, "y": 10},
                        {"x": 60, "y": 20},
                        {"x": 50, "y": 20},
                    ],
                },
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    response = client.get(
        _url(project["id"], image_id),
        params={"columns": 4, "rows": 3},
    )
    assert response.status_code == 200, response.text

    layers = {item["kind"]: item for item in response.json()["layers"]}

    boxes = layers["reviewed_boxes"]
    masks = layers["verified_masks"]
    predictions = layers["pending_predictions"]

    assert boxes["object_count"] == 1
    assert boxes["counts"][0][0] == 1

    assert masks["object_count"] == 1
    assert masks["counts"][1][1] == 1

    assert predictions["object_count"] == 0

    filtered = client.get(
        _url(project["id"], image_id),
        params={
            "columns": 4,
            "rows": 3,
            "label_class_id": label_id,
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["label_class_id"] == label_id


def test_wrong_project_and_invalid_grid_rejected(
    client: TestClient,
) -> None:
    first = create_project(client, "First")
    other = create_project(client, "Other")

    image_id = import_one(client, first["id"])["successful"][0]["image_id"]

    assert client.get(_url(other["id"], image_id)).status_code == 404

    assert (
        client.get(
            _url(first["id"], image_id),
            params={"columns": 1000},
        ).status_code
        == 422
    )

    assert (
        client.get(
            _url(first["id"], image_id),
            params={
                "label_class_id": other["label_classes"][0]["id"],
            },
        ).status_code
        == 404
    )


def test_unreviewed_image_boxes_do_not_claim_reviewed_status(
    client: TestClient,
) -> None:
    project = create_project(client, "Review gate")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]

    save = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "annotated",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 15,
                    "y_max": 15,
                }
            ],
        },
    )
    assert save.status_code == 200, save.text

    data = client.get(_url(project["id"], image_id)).json()

    reviewed = next(layer for layer in data["layers"] if layer["kind"] == "reviewed_boxes")
    assert reviewed["object_count"] == 0
    assert data["annotation_status"] == "annotated"
