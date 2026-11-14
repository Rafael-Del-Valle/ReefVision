"""ReefVision 1.1 annotation aggregate regression tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.db.models import MaskAnnotation
from reefvision.tests.test_annotations import (
    create_project,
    import_one,
)


def test_annotation_aggregate_counts(
    client: TestClient,
) -> None:
    project = create_project(client, "Aggregate study")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]

    label_id = project["label_classes"][0]["id"]
    url = f"/api/v1/projects/{project['id']}/images/{image_id}/annotation-aggregates"

    empty = client.get(url)
    assert empty.status_code == 200, empty.text
    assert empty.json()["total_saved_box_count"] == 0

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "annotated",
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
                        {"x": 5, "y": 5},
                        {"x": 25, "y": 5},
                        {"x": 25, "y": 20},
                        {"x": 5, "y": 20},
                    ],
                },
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "status": "draft",
                    "points": [
                        {"x": 35, "y": 5},
                        {"x": 45, "y": 5},
                        {"x": 45, "y": 15},
                        {"x": 35, "y": 15},
                    ],
                },
            ],
        },
    )

    assert saved.status_code == 200, saved.text

    response = client.get(url)
    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total_saved_box_count"] == 1
    assert data["total_verified_mask_count"] == 1
    assert data["total_unverified_mask_count"] == 1

    cls = next(row for row in data["classes"] if row["label_class_id"] == label_id)

    assert cls["box_count"] == 1
    assert cls["verified_mask_count"] == 1
    assert cls["known_mask_area_px2_sum"] == 300
    assert cls["verified_masks_by_geometry"] == {"polygon": 1}

    assert len(data["snapshot_sha256"]) == 64
    assert data["snapshot_sha256"] != (empty.json()["snapshot_sha256"])
    assert client.get(url).json()["snapshot_sha256"] == data["snapshot_sha256"]


def test_cross_project_access_rejected(
    client: TestClient,
) -> None:
    first = create_project(client, "First project")
    second = create_project(client, "Second project")

    image_id = import_one(client, first["id"])["successful"][0]["image_id"]

    url = f"/api/v1/projects/{second['id']}/images/{image_id}/annotation-aggregates"

    assert client.get(url).status_code == 404


def test_corrupt_mask_area_rejected(
    client: TestClient,
) -> None:
    project = create_project(client, "Mask integrity")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]

    mask_id = str(uuid4())
    label_id = project["label_classes"][0]["id"]

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "annotated",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 2, "y": 2},
                        {"x": 12, "y": 2},
                        {"x": 12, "y": 12},
                        {"x": 2, "y": 12},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    url = f"/api/v1/projects/{project['id']}/images/{image_id}/annotation-aggregates"

    with client.app.state.session_factory() as session:
        row = session.get(MaskAnnotation, mask_id)
        assert row is not None
        row.area_pixels = 999_999
        session.commit()

    response = client.get(url)
    assert response.status_code == 400
    assert "invalid source-pixel area" in (response.json()["detail"])
