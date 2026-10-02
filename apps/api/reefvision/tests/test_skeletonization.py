from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models import MaskAnnotation
from reefvision.services.skeletonization import (
    SkeletonizationService,
    _connected_components_8,
)
from reefvision.tests.test_annotations import create_project, import_one


def _save_polygon(
    client: TestClient,
    *,
    image_id: str,
    class_id: str,
    mask_id: str,
) -> None:
    response = client.put(
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
    assert response.status_code == 200, response.text


def _readiness(client: TestClient, mask_id: str) -> dict[str, object]:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        response = SkeletonizationService(
            session,
            app.state.settings,
        ).readiness(mask_id)
        return response.model_dump(mode="json")


def test_diagonal_pixels_are_one_component_under_eight_connectivity() -> None:
    data = bytearray(16)
    data[1 * 4 + 1] = 255
    data[2 * 4 + 2] = 255

    components = _connected_components_8((bytes(data), 4, 4))

    assert len(components) == 1
    assert components[0].pixel_count == 2


def test_verified_single_component_polygon_is_ready(client: TestClient) -> None:
    project = create_project(client, "Skeleton readiness polygon")
    report = import_one(client, project["id"], size=(64, 64))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "61cfba75-996d-4bc9-ac13-b28c096651ca"
    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=mask_id,
    )

    payload = _readiness(client, mask_id)

    assert payload["connectivity"] == 8
    assert payload["component_count"] == 1
    assert payload["single_component"] is True
    assert payload["ready_for_skeletonization"] is True
    assert payload["blocking_reason"] is None
    assert payload["resolution_actions"] == []
    assert payload["automatic_bridge_applied"] is False


def test_disconnected_raster_is_blocked_without_silent_bridging(
    client: TestClient,
) -> None:
    project = create_project(client, "Skeleton readiness disconnected raster")
    report = import_one(client, project["id"], size=(64, 64))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "7553d6b7-9424-4526-a30c-93904e4b76f6"

    app = cast(FastAPI, client.app)
    relative_path = (
        f"projects/{project['id']}/masks/{image_id}/{mask_id}-skeleton-readiness.png"
    )
    mask_path = app.state.settings.resolved_data_dir / Path(relative_path)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    raster = Image.new("L", (64, 64), 0)
    for x in range(8, 16):
        for y in range(8, 16):
            raster.putpixel((x, y), 255)
    for x in range(40, 48):
        for y in range(40, 48):
            raster.putpixel((x, y), 255)
    raster.save(mask_path)

    with app.state.session_factory() as session:
        session.add(
            MaskAnnotation(
                id=mask_id,
                image_id=image_id,
                label_class_id=class_id,
                geometry_kind="raster_mask",
                mask_path=relative_path,
                x_min=8,
                y_min=8,
                x_max=47,
                y_max=47,
                area_pixels=128,
                status="verified",
            )
        )
        session.commit()

    payload = _readiness(client, mask_id)

    assert payload["component_count"] == 2
    assert payload["single_component"] is False
    assert payload["ready_for_skeletonization"] is False
    assert payload["blocking_reason"] == "multiple_components"
    assert payload["resolution_actions"] == [
        "repair_gap",
        "delete_artifact",
        "classify_separate_object",
    ]
    assert payload["automatic_bridge_applied"] is False
    components = cast(list[dict[str, object]], payload["components"])
    assert [component["pixel_count"] for component in components] == [64, 64]


def test_unverified_mask_is_not_ready_even_when_connected(client: TestClient) -> None:
    project = create_project(client, "Skeleton readiness approval gate")
    report = import_one(client, project["id"], size=(64, 64))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "1c420b5a-d377-4d03-9f6a-9b95370a791b"
    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=mask_id,
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.status = "draft"
        session.commit()

    payload = _readiness(client, mask_id)

    assert payload["component_count"] == 1
    assert payload["ready_for_skeletonization"] is False
    assert payload["blocking_reason"] == "mask_not_verified"
    assert payload["automatic_bridge_applied"] is False



def test_connected_raster_mask_runs_full_structure_analysis(
    client: TestClient,
) -> None:
    project = create_project(client, "Skeleton connected raster analysis")
    report = import_one(client, project["id"], size=(64, 64))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "19d879db-01a8-467c-9037-f9d010539ec4"

    app = cast(FastAPI, client.app)
    relative_path = (
        f"projects/{project['id']}/masks/{image_id}/{mask_id}-connected.png"
    )
    mask_path = app.state.settings.resolved_data_dir / Path(relative_path)
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    raster = Image.new("L", (64, 64), 0)
    for x in range(10, 51):
        for y in range(28, 35):
            raster.putpixel((x, y), 255)
    raster.save(mask_path)

    with app.state.session_factory() as session:
        session.add(
            MaskAnnotation(
                id=mask_id,
                image_id=image_id,
                label_class_id=class_id,
                geometry_kind="raster_mask",
                mask_path=relative_path,
                x_min=10,
                y_min=28,
                x_max=50,
                y_max=34,
                area_pixels=287,
                status="verified",
            )
        )
        session.commit()

    response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/structure-analysis"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mask_annotation_id"] == mask_id
    assert payload["raw_skeleton_component_count"] == 1
    assert payload["topology_preserved"] is True
    assert payload["raw_skeleton_pixel_count"] > 1
    assert payload["raw_branch_count"] == 1
    assert payload["final_branch_count"] == 1
    assert payload["final_skeleton_source"] == "automatic_pruned"
