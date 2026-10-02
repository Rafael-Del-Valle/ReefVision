from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def test_structure_readiness_endpoint_reports_single_component(
    client: TestClient,
) -> None:
    project = create_project(client, "Coral structure API")
    report = import_one(client, project["id"], size=(64, 64))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "f1326b34-49fb-4fe5-a992-094741346a7b"

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 10},
                        {"x": 40, "y": 10},
                        {"x": 40, "y": 40},
                        {"x": 10, "y": 40},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/structure-readiness"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "skeleton-readiness-0001"
    assert payload["connectivity"] == 8
    assert payload["component_count"] == 1
    assert payload["ready_for_skeletonization"] is True
    assert payload["automatic_bridge_applied"] is False
