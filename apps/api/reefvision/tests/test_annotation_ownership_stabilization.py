from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def test_box_annotation_id_cannot_be_reused_across_images(
    client: TestClient,
) -> None:
    project = create_project(client, "Annotation ownership")
    first = import_one(
        client,
        project["id"],
        filename="first.png",
        relative_path="ownership/first.png",
        size=(80, 60),
    )
    second = import_one(
        client,
        project["id"],
        filename="second.png",
        relative_path="ownership/second.png",
        size=(81, 60),
    )
    first_image_id = first["successful"][0]["image_id"]
    second_image_id = second["successful"][0]["image_id"]
    annotation_id = "b33c9be7-2d1c-4c5d-b251-90a47f91f6a7"
    label_class_id = project["label_classes"][0]["id"]

    created = client.put(
        f"/api/v1/images/{first_image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": annotation_id,
                    "label_class_id": label_class_id,
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 20,
                    "y_max": 20,
                }
            ],
        },
    )
    assert created.status_code == 200, created.text

    reused = client.put(
        f"/api/v1/images/{second_image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [
                {
                    "id": annotation_id,
                    "label_class_id": label_class_id,
                    "x_min": 6,
                    "y_min": 6,
                    "x_max": 21,
                    "y_max": 21,
                }
            ],
        },
    )

    assert reused.status_code == 400, reused.text
    assert "source image" in reused.json()["detail"]

    first_session = client.get(
        f"/api/v1/images/{first_image_id}/annotations"
    ).json()
    second_session = client.get(
        f"/api/v1/images/{second_image_id}/annotations"
    ).json()
    assert first_session["image"]["annotation_revision"] == 1
    assert first_session["annotations"][0]["id"] == annotation_id
    assert second_session["image"]["annotation_revision"] == 0
    assert second_session["annotations"] == []
