from __future__ import annotations

import json
import zipfile
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.export import process_export_job
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version


def test_coco_export_contains_immutable_boxes_polygons_and_categories(
    client: TestClient,
) -> None:
    project = create_project(client, "COCO interoperability")
    imported = import_one(client, str(project["id"]), size=(80, 60))
    image_id = str(imported["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": "9a97524f-52da-4145-a638-086e0bd637b1",
                    "label_class_id": label_class_id,
                    "x_min": 5,
                    "y_min": 6,
                    "x_max": 25,
                    "y_max": 26,
                }
            ],
            "mask_annotations": [
                {
                    "id": "abde810d-748a-471d-9c7b-bbb5199e0085",
                    "label_class_id": label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 30, "y": 10},
                        {"x": 50, "y": 10},
                        {"x": 50, "y": 30},
                        {"x": 30, "y": 30},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    version = create_version(client, str(project["id"]), name="COCO snapshot")
    items = client.get(f"/api/v1/dataset-versions/{version['id']}/items")
    assert items.status_code == 200, items.text
    split = str(items.json()[0]["split"])

    created = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={"format": "coco_instances"},
    )
    assert created.status_code == 200, created.text
    export = created.json()["export"]
    job = created.json()["job"]
    app = cast(FastAPI, client.app)
    assert process_export_job(
        app.state.settings,
        app.state.session_factory,
        job["id"],
    )

    archive_path = app.state.settings.resolved_data_dir / export["archive_path"]
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        annotation_name = f"annotations/instances_{split}.json"
        assert annotation_name in names
        coco = json.loads(archive.read(annotation_name))
        manifest = json.loads(archive.read("export-manifest.json"))

    assert len(coco["images"]) == 1
    assert coco["images"][0]["reefvision_image_id"] == image_id
    assert len(coco["categories"]) == len(project["label_classes"])
    assert len(coco["annotations"]) == 2
    by_geometry = {
        item["reefvision_geometry_kind"]: item
        for item in coco["annotations"]
    }
    box = by_geometry["bounding_box"]
    assert box["bbox"] == [5.0, 6.0, 20.0, 20.0]
    assert box["area"] == 400
    assert box["segmentation"] == []
    polygon = by_geometry["polygon"]
    assert polygon["bbox"] == [30.0, 10.0, 20.0, 20.0]
    assert polygon["area"] == 400
    assert polygon["segmentation"] == [
        [30.0, 10.0, 50.0, 10.0, 50.0, 30.0, 30.0, 30.0]
    ]
    assert manifest["format"] == "coco_instances"
    assert manifest["box_annotation_count"] == 1
    assert manifest["mask_annotation_count"] == 1
