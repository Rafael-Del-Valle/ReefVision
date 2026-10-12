from __future__ import annotations

import json
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

    updated_image = update_image(
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
        base_revision=int(updated_image["annotation_revision"]),
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


def test_brush_object_vectorizes_into_yolo_segmentation_export(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Brush YOLO export")
    report = import_image(
        client,
        project["id"],
        filename="brush.png",
        relative_path="brush/brush.png",
        color=(25, 80, 135),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    _brush(
        client,
        image_id=image_id,
        class_id=class_id,
        base_revision=0,
        x=20,
        y=20,
    )
    update_image(
        client,
        image_id,
        group_key="fragment-1",
        annotation_status="reviewed",
    )
    version = create_version(client, project["id"], name="Brush YOLO snapshot")

    queued = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={"format": "yolo_segmentation"},
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
    label_files = sorted(output_root.glob("labels/*/*.txt"))
    assert len(label_files) == 1
    assert label_files[0].read_text(encoding="utf-8").strip().startswith("0 ")

    manifest_path = test_settings.resolved_data_dir / Path(export["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["vectorized_raster_count"] == 1
    assert manifest["skipped_raster_count"] == 0


def test_full_erase_deletes_raster_mask_object(
    client: TestClient,
    test_settings: Settings,
) -> None:
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
    original_path = test_settings.resolved_data_dir / Path(str(mask["mask_path"]))
    original_bytes = original_path.read_bytes()

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

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mask_annotation"]["deleted_at"] is not None
    assert payload["mask_annotation"]["revision"] == 2
    assert payload["mask_annotation"]["provenance_json"]["deleted_by_full_erase"] is True
    assert payload["image"]["annotation_revision"] == 2

    session = client.get(f"/api/v1/images/{image_id}/annotations")
    assert session.status_code == 200, session.text
    assert session.json()["mask_annotations"] == []

    assert original_path.is_file()
    assert original_path.read_bytes() == original_bytes


def test_raster_mask_class_can_be_reassigned_without_repainting(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Raster class reassignment")
    report = import_image(
        client,
        project["id"],
        filename="painted.png",
        relative_path="painted/painted.png",
        color=(25, 80, 135),
    )
    image_id = report["successful"][0]["image_id"]
    first_class_id = project["label_classes"][0]["id"]
    second_class_id = project["label_classes"][1]["id"]

    created = _brush(
        client,
        image_id=image_id,
        class_id=first_class_id,
        base_revision=0,
        x=20,
        y=20,
    )
    mask = cast(dict[str, object], created["mask_annotation"])
    mask_id = str(mask["id"])
    mask_path = test_settings.resolved_data_dir / Path(str(mask["mask_path"]))
    original_bytes = mask_path.read_bytes()

    response = client.patch(
        f"/api/v1/images/{image_id}/raster-mask-annotations/{mask_id}/class",
        json={
            "base_revision": 1,
            "label_class_id": second_class_id,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["image"]["annotation_revision"] == 2
    assert payload["mask_annotation"]["label_class_id"] == second_class_id
    assert payload["mask_annotation"]["revision"] == 2
    assert Path(str(payload["mask_annotation"]["mask_path"])).name == mask_path.name
    assert mask_path.read_bytes() == original_bytes

    reloaded = client.get(f"/api/v1/images/{image_id}/annotations")
    assert reloaded.status_code == 200
    saved_mask = reloaded.json()["mask_annotations"][0]
    assert saved_mask["label_class_id"] == second_class_id
    assert saved_mask["revision"] == 2


def test_raster_mask_duplicate_copies_immutable_pixels_without_verification(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Raster clipboard duplicate")
    report = import_image(
        client,
        project["id"],
        filename="copy.png",
        relative_path="raster/copy.png",
        color=(25, 80, 135),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    created = _brush(
        client,
        image_id=image_id,
        class_id=class_id,
        base_revision=0,
        x=20,
        y=20,
    )
    source = cast(dict[str, object], created["mask_annotation"])

    response = client.post(
        f"/api/v1/images/{image_id}/raster-mask-annotations/{source['id']}/duplicate",
        json={"base_revision": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    duplicate = payload["mask_annotation"]
    assert payload["image"]["annotation_revision"] == 2
    assert duplicate["id"] != source["id"]
    assert duplicate["label_class_id"] == class_id
    assert duplicate["status"] == "draft"
    assert duplicate["source_type"] == "human_copy"
    assert duplicate["provenance_json"] is None
    assert duplicate["revision"] == 1
    assert duplicate["mask_path"] != source["mask_path"]
    source_path = test_settings.resolved_data_dir / Path(str(source["mask_path"]))
    duplicate_path = test_settings.resolved_data_dir / Path(str(duplicate["mask_path"]))
    assert duplicate_path.read_bytes() == source_path.read_bytes()
    reloaded = client.get(f"/api/v1/images/{image_id}/annotations")
    assert reloaded.status_code == 200, reloaded.text
    saved_copy = next(
        item for item in reloaded.json()["mask_annotations"] if item["id"] == duplicate["id"]
    )
    assert saved_copy["status"] == "draft"
    assert saved_copy["provenance_json"] is None

    update_image(
        client,
        image_id,
        group_key="fragment-copy",
        annotation_status="reviewed",
    )
    version = create_version(client, project["id"], name="Verified copy guard")
    assert version["mask_annotation_count"] == 1


def test_raster_duplicate_marks_reviewed_image_in_progress(
    client: TestClient,
) -> None:
    project = create_project(client, "Raster review invalidation")
    report = import_image(
        client,
        project["id"],
        filename="reviewed-source.png",
        relative_path="raster/reviewed-source.png",
        color=(25, 80, 135),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    created = _brush(
        client,
        image_id=image_id,
        class_id=class_id,
        base_revision=0,
        x=20,
        y=20,
    )
    source = cast(dict[str, object], created["mask_annotation"])
    reviewed = update_image(
        client,
        image_id,
        group_key="review-invalidation",
        annotation_status="reviewed",
    )
    assert reviewed["annotation_status"] == "reviewed"

    response = client.post(
        f"/api/v1/images/{image_id}/raster-mask-annotations/{source['id']}/duplicate",
        json={"base_revision": reviewed["annotation_revision"]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["image"]["annotation_status"] == "in_progress"
    assert result["mask_annotation"]["status"] == "draft"
    assert result["mask_annotation"]["source_type"] == "human_copy"

    current = client.get(f"/api/v1/images/{image_id}/annotations")
    assert current.status_code == 200, current.text
    assert current.json()["image"]["annotation_status"] == "in_progress"
    copied_id = result["mask_annotation"]["id"]
    assert any(
        item["id"] == copied_id and item["status"] == "draft"
        for item in current.json()["mask_annotations"]
    )
