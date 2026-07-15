from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.jobs.export import process_export_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import (
    create_version,
    import_image,
    update_image,
)


def _brush(
    client: TestClient,
    *,
    image_id: str,
    class_id: str,
    base_revision: int,
    x: float,
    y: float,
    mask_id: str | None = None,
    mode: str = "paint",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": base_revision,
            "mask_annotation_id": mask_id,
            "label_class_id": class_id,
            "mode": mode,
            "brush_radius": 5,
            "strokes": [{"points": [{"x": x, "y": y}]}],
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def test_raster_brush_revisions_preserve_frozen_semantic_exports(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Raster revision study")
    report = import_image(
        client,
        project["id"],
        filename="raster.png",
        relative_path="raster/raster.png",
        color=(25, 80, 135),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    first = _brush(
        client,
        image_id=image_id,
        class_id=class_id,
        base_revision=0,
        x=20,
        y=20,
    )
    first_mask = cast(dict[str, object], first["mask_annotation"])
    mask_id = str(first_mask["id"])
    first_path = test_settings.resolved_data_dir / Path(str(first_mask["mask_path"]))
    assert first_mask["revision"] == 1
    assert first_path.is_file()
    first_bytes = first_path.read_bytes()

    update_image(
        client,
        image_id,
        group_key="fragment-1",
        annotation_status="reviewed",
    )
    version = create_version(client, project["id"], name="Raster snapshot")
    assert version["mask_annotation_count"] == 1

    second = _brush(
        client,
        image_id=image_id,
        class_id=class_id,
        base_revision=1,
        x=45,
        y=30,
        mask_id=mask_id,
    )
    second_mask = cast(dict[str, object], second["mask_annotation"])
    second_path = test_settings.resolved_data_dir / Path(str(second_mask["mask_path"]))
    assert second_mask["revision"] == 2
    assert second_path != first_path
    assert first_path.read_bytes() == first_bytes
    assert second_path.is_file()

    queued = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={"format": "semantic_masks"},
    )
    assert queued.status_code == 200, queued.text
    payload = queued.json()
    app = cast(FastAPI, client.app)
    assert process_export_job(
        app.state.settings,
        app.state.session_factory,
        payload["job"]["id"],
    )
    export = client.get(f"/api/v1/exports/{payload['export']['id']}").json()
    output_root = test_settings.resolved_data_dir / Path(export["output_path"])
    exported_masks = sorted(output_root.glob("masks/*/*.png"))
    assert len(exported_masks) == 1
    with Image.open(exported_masks[0]) as semantic:
        assert semantic.getpixel((20, 20)) == 1
        assert semantic.getpixel((45, 30)) == 0


def test_eraser_rejects_empty_raster_mask(client: TestClient) -> None:
    project = create_project(client, "Raster eraser study")
    report = import_image(
        client,
        project["id"],
        filename="erase.png",
        relative_path="raster/erase.png",
        color=(35, 90, 145),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    first = _brush(
        client,
        image_id=image_id,
        class_id=class_id,
        base_revision=0,
        x=20,
        y=20,
    )
    mask = cast(dict[str, object], first["mask_annotation"])

    response = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": 1,
            "mask_annotation_id": mask["id"],
            "label_class_id": class_id,
            "mode": "erase",
            "brush_radius": 20,
            "strokes": [{"points": [{"x": 20, "y": 20}]}],
        },
    )
    assert response.status_code == 400
    assert "empty mask" in response.json()["detail"]
