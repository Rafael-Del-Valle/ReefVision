from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def test_polygon_rejects_duplicate_closing_vertex_transactionally(
    client: TestClient,
) -> None:
    project = create_project(client, "Duplicate polygon vertices")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": "632cf708-f02b-4cd1-a445-d976e5c2a756",
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 5, "y": 5},
                        {"x": 25, "y": 5},
                        {"x": 25, "y": 20},
                        {"x": 5, "y": 20},
                        {"x": 5, "y": 5},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()

    session = client.get(f"/api/v1/images/{image_id}/annotations")
    assert session.status_code == 200
    assert session.json()["mask_annotations"] == []
    assert session.json()["image"]["annotation_revision"] == 0
