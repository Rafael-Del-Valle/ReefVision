from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import MaskAnnotationEvent
from reefvision.tests.test_annotations import create_project, import_one


def test_cleanup_removes_small_disconnected_components(client: TestClient) -> None:
    project = create_project(client, "Raster component cleanup")
    imported = import_one(client, str(project["id"]), size=(64, 64))
    image_id = str(imported["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])

    created = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": 0,
            "label_class_id": label_class_id,
            "mode": "paint",
            "brush_radius": 2,
            "strokes": [
                {"points": [{"x": 5, "y": 10}, {"x": 30, "y": 10}]},
                {"points": [{"x": 50, "y": 50}]},
            ],
        },
    )
    assert created.status_code == 200, created.text
    created_mask = created.json()["mask_annotation"]

    cleaned = client.post(
        f"/api/v1/images/{image_id}/raster-mask-cleanup",
        json={
            "base_revision": 1,
            "mask_annotation_id": created_mask["id"],
            "remove_small_components": True,
            "minimum_component_area": 30,
            "keep_largest_component": False,
            "fill_holes": False,
            "connectivity": 8,
        },
    )
    assert cleaned.status_code == 200, cleaned.text
    cleaned_mask = cleaned.json()["mask_annotation"]
    assert cleaned_mask["revision"] == 2
    assert cleaned_mask["area_pixels"] < created_mask["area_pixels"]
    statistics = cleaned_mask["provenance_json"]["last_cleanup"]
    assert statistics["original_component_count"] == 2
    assert statistics["cleaned_component_count"] == 1
    assert statistics["removed_component_count"] == 1


def test_cleanup_fills_holes_and_records_audit_event(client: TestClient) -> None:
    project = create_project(client, "Raster hole cleanup")
    imported = import_one(client, str(project["id"]), size=(64, 64))
    image_id = str(imported["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])

    created = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": 0,
            "label_class_id": label_class_id,
            "mode": "paint",
            "brush_radius": 12,
            "strokes": [{"points": [{"x": 30, "y": 30}]}],
        },
    )
    assert created.status_code == 200, created.text
    mask_id = str(created.json()["mask_annotation"]["id"])

    erased = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": 1,
            "mask_annotation_id": mask_id,
            "label_class_id": label_class_id,
            "mode": "erase",
            "brush_radius": 4,
            "strokes": [{"points": [{"x": 30, "y": 30}]}],
        },
    )
    assert erased.status_code == 200, erased.text
    erased_area = int(erased.json()["mask_annotation"]["area_pixels"])

    cleaned = client.post(
        f"/api/v1/images/{image_id}/raster-mask-cleanup",
        json={
            "base_revision": 2,
            "mask_annotation_id": mask_id,
            "remove_small_components": False,
            "minimum_component_area": 1,
            "keep_largest_component": False,
            "fill_holes": True,
            "connectivity": 8,
        },
    )
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["mask_annotation"]["area_pixels"] > erased_area
    assert cleaned.json()["image"]["annotation_revision"] == 3

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(MaskAnnotationEvent)
                .where(MaskAnnotationEvent.mask_annotation_id == mask_id)
                .order_by(MaskAnnotationEvent.created_at, MaskAnnotationEvent.id)
            )
        )
    assert [event.event_type for event in events] == [
        "created",
        "updated",
        "topology_cleaned",
    ]
