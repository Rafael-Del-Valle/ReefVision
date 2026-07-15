from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import MaskAnnotation, MaskAnnotationEvent
from reefvision.tests.test_annotations import create_project, import_one


def _mask_payload(
    mask_id: str,
    label_class_id: str,
    points: list[tuple[float, float]],
) -> dict[str, Any]:
    return {
        "id": mask_id,
        "label_class_id": label_class_id,
        "geometry_kind": "polygon",
        "points": [{"x": x, "y": y} for x, y in points],
    }


def test_polygon_mask_create_update_delete_and_audit(client: TestClient) -> None:
    project = create_project(client, "Mask lifecycle")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    mask_id = "97c82814-f977-497a-896d-832a247df107"
    first_class_id = project["label_classes"][0]["id"]
    second_class_id = project["label_classes"][1]["id"]

    created = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                _mask_payload(
                    mask_id,
                    first_class_id,
                    [(5, 5), (25, 5), (25, 20), (5, 20)],
                )
            ],
        },
    )
    assert created.status_code == 200, created.text
    created_payload = created.json()
    assert created_payload["image"]["annotation_revision"] == 1
    assert created_payload["mask_annotations"][0]["area_pixels"] == 300
    assert created_payload["mask_counts_by_class"][0]["count"] == 1

    updated = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 1,
            "annotation_status": "annotated",
            "annotations": [],
            "mask_annotations": [
                _mask_payload(
                    mask_id,
                    second_class_id,
                    [(6, 6), (30, 6), (30, 24), (6, 24)],
                )
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["mask_annotations"][0]["revision"] == 2
    assert updated.json()["mask_annotations"][0]["label_class_id"] == second_class_id

    deleted = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 2,
            "annotation_status": "annotated",
            "annotations": [],
            "deleted_mask_annotation_ids": [mask_id],
        },
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["mask_annotations"] == []

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        assert mask.deleted_at is not None
        assert mask.revision == 3
        events = session.scalars(
            select(MaskAnnotationEvent)
            .where(MaskAnnotationEvent.mask_annotation_id == mask_id)
            .order_by(MaskAnnotationEvent.created_at, MaskAnnotationEvent.id)
        )
        assert [event.event_type for event in events] == [
            "created",
            "class_changed",
            "deleted",
        ]


def test_polygon_mask_validation_is_transactional(client: TestClient) -> None:
    project = create_project(client, "Mask validation")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]

    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                _mask_payload(
                    "ff9c9278-e0ad-45d3-a45f-c7752d7e529d",
                    label_class_id,
                    [(5, 5), (30, 25), (5, 25), (30, 5)],
                )
            ],
        },
    )
    assert response.status_code == 400
    assert "self-intersect" in response.json()["detail"]

    out_of_bounds = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                _mask_payload(
                    "69994196-d634-42ca-8740-dad66fab856c",
                    label_class_id,
                    [(-1, 1), (10, 1), (10, 10)],
                )
            ],
        },
    )
    assert out_of_bounds.status_code == 400
    assert "outside the image" in out_of_bounds.json()["detail"]

    session_payload = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert session_payload["mask_annotations"] == []
    assert session_payload["image"]["annotation_revision"] == 0


def test_box_only_save_preserves_existing_masks(client: TestClient) -> None:
    project = create_project(client, "Backward compatibility")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    mask_id = "e91e674d-cc1e-4427-8710-a20b4bb7202d"

    created = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                _mask_payload(
                    mask_id,
                    label_class_id,
                    [(5, 5), (20, 5), (20, 20), (5, 20)],
                )
            ],
        },
    )
    assert created.status_code == 200

    legacy_save = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 1,
            "annotation_status": "annotated",
            "annotations": [
                {
                    "id": "dd232ae5-2777-4499-800f-5ead48c3bda7",
                    "label_class_id": label_class_id,
                    "x_min": 1,
                    "y_min": 1,
                    "x_max": 10,
                    "y_max": 10,
                }
            ],
        },
    )
    assert legacy_save.status_code == 200, legacy_save.text
    assert [mask["id"] for mask in legacy_save.json()["mask_annotations"]] == [
        mask_id
    ]


def test_mask_save_uses_shared_revision_conflict_protection(client: TestClient) -> None:
    project = create_project(client, "Mask revision")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]

    first = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                _mask_payload(
                    "2fb0beb0-a94d-4a30-b506-c932459b4094",
                    label_class_id,
                    [(5, 5), (20, 5), (20, 20)],
                )
            ],
        },
    )
    assert first.status_code == 200

    stale = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "deleted_mask_annotation_ids": [
                "2fb0beb0-a94d-4a30-b506-c932459b4094"
            ],
        },
    )
    assert stale.status_code == 409
    assert "revision conflict" in stale.json()["detail"].lower()
