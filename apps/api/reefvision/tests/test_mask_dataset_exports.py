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
from reefvision.tests.test_dataset_versions import create_version, import_image


def _save_polygon(
    client: TestClient,
    *,
    image_id: str,
    class_id: str,
    mask_id: str,
    points: list[tuple[float, float]],
    base_revision: int,
) -> dict[str, object]:
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": base_revision,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [{"x": x, "y": y} for x, y in points],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def _run_export(
    client: TestClient,
    *,
    version_id: str,
    export_format: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/dataset-versions/{version_id}/exports",
        json={"format": export_format},
    )
    assert response.status_code == 200, response.text
    payload = cast(dict[str, object], response.json())
    job = cast(dict[str, object], payload["job"])
    app = cast(FastAPI, client.app)
    assert process_export_job(
        app.state.settings,
        app.state.session_factory,
        str(job["id"]),
    )
    export = cast(dict[str, object], payload["export"])
    result = client.get(f"/api/v1/exports/{export['id']}")
    assert result.status_code == 200, result.text
    return cast(dict[str, object], result.json())


def test_dataset_version_freezes_polygon_masks(client: TestClient) -> None:
    project = create_project(client, "Frozen mask study")
    report = import_image(
        client,
        project["id"],
        filename="mask.png",
        relative_path="masks/mask.png",
        color=(20, 90, 120),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "d57acaa2-661f-4d9a-a3dc-50dd5d3d21d4"

    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=mask_id,
        points=[(10, 10), (30, 10), (30, 30), (10, 30)],
        base_revision=0,
    )
    version = create_version(client, project["id"], name="Frozen masks")

    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=mask_id,
        points=[(12, 12), (36, 12), (36, 36), (12, 36)],
        base_revision=1,
    )

    items = client.get(f"/api/v1/dataset-versions/{version['id']}/items")
    assert items.status_code == 200, items.text
    item = items.json()[0]
    assert version["mask_annotation_count"] == 1
    assert item["mask_annotation_count"] == 1
    assert item["per_mask_class_counts_json"] == {class_id: 1}
    assert item["mask_annotation_snapshot_json"][0]["polygon_json"] == [
        [10.0, 10.0],
        [30.0, 10.0],
        [30.0, 30.0],
        [10.0, 30.0],
    ]


def test_yolo_segmentation_export_uses_frozen_polygon_snapshot(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "YOLO segmentation study")
    report = import_image(
        client,
        project["id"],
        filename="segment.png",
        relative_path="segment/segment.png",
        color=(40, 100, 150),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id="ca2608aa-48d0-4105-8d9b-42dacfaa02db",
        points=[(8, 6), (40, 6), (40, 30), (8, 30)],
        base_revision=0,
    )
    version = create_version(
        client,
        project["id"],
        name="YOLO segment snapshot",
    )
    export = _run_export(
        client,
        version_id=version["id"],
        export_format="yolo_segmentation",
    )

    output_root = test_settings.resolved_data_dir / Path(str(export["output_path"]))
    label_files = sorted(output_root.glob("labels/*/*.txt"))
    assert len(label_files) == 1
    assert label_files[0].read_text(encoding="utf-8") == (
        "0 0.10000000 0.10000000 0.50000000 0.10000000 0.50000000 0.50000000 0.10000000 0.50000000"
    )
    data_yaml = (output_root / "data.yaml").read_text(encoding="utf-8")
    assert "path:" not in data_yaml
    assert "train: images/train" in data_yaml
    assert "val: images/validation" in data_yaml
    manifest_file = test_settings.resolved_data_dir / Path(str(export["manifest_path"]))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["format"] == "yolo_segmentation"
    assert manifest["polygon_count"] == 1


def test_semantic_export_writes_indexed_class_pixels(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Semantic mask study")
    report = import_image(
        client,
        project["id"],
        filename="semantic.png",
        relative_path="semantic/semantic.png",
        color=(55, 105, 160),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id="06cfa889-cd6d-449d-a164-9fc59550ae55",
        points=[(10, 10), (30, 10), (30, 25), (10, 25)],
        base_revision=0,
    )
    version = create_version(client, project["id"], name="Semantic snapshot")
    export = _run_export(
        client,
        version_id=version["id"],
        export_format="semantic_masks",
    )

    output_root = test_settings.resolved_data_dir / Path(str(export["output_path"]))
    mask_files = sorted(output_root.glob("masks/*/*.png"))
    assert len(mask_files) == 1
    with Image.open(mask_files[0]) as semantic:
        assert semantic.mode == "P"
        assert semantic.getpixel((15, 15)) == 1
        assert semantic.getpixel((2, 2)) == 0
