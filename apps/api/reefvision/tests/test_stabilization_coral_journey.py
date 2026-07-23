from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.config import Settings
from reefvision.jobs.export import process_export_job
from reefvision.jobs.worker import process_thumbnail_job
from reefvision.main import create_app
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import create_version, update_image


def _coral_image_bytes(*, image_format: str, offset: int) -> bytes:
    image = Image.new("RGB", (160, 120), (8, 24, 38))
    draw = ImageDraw.Draw(image)
    draw.line(
        [(25 + offset, 108), (44 + offset, 78), (62 + offset, 48), (82 + offset, 18)],
        fill=(224, 126, 96),
        width=8,
    )
    draw.line(
        [(53 + offset, 62), (31 + offset, 41), (18 + offset, 23)],
        fill=(224, 126, 96),
        width=6,
    )
    draw.line(
        [(67 + offset, 42), (93 + offset, 30), (112 + offset, 15)],
        fill=(224, 126, 96),
        width=6,
    )
    stream = BytesIO()
    image.save(stream, format=image_format)
    return stream.getvalue()


def _import_coral_image(
    client: TestClient,
    project_id: str,
    *,
    filename: str,
    relative_path: str,
    image_format: str,
    offset: int,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[
            (
                "files",
                (
                    filename,
                    _coral_image_bytes(image_format=image_format, offset=offset),
                    "application/octet-stream",
                ),
            )
        ],
        data={"relative_paths": relative_path},
    )
    assert response.status_code == 200, response.text
    payload = cast(dict[str, Any], response.json())
    assert len(payload["successful"]) == 1
    assert payload["failed"] == []
    item = cast(dict[str, Any], payload["successful"][0])
    assert item["thumbnail_job_id"]
    return item


def _save_reviewed_coral_annotation(
    client: TestClient,
    *,
    image_id: str,
    label_class_id: str,
    annotation_id: str,
    mask_id: str | None,
) -> None:
    payload: dict[str, Any] = {
        "base_revision": 0,
        "annotation_status": "reviewed",
        "annotations": [
            {
                "id": annotation_id,
                "label_class_id": label_class_id,
                "x_min": 14,
                "y_min": 12,
                "x_max": 124,
                "y_max": 112,
            }
        ],
    }
    if mask_id is not None:
        payload["mask_annotations"] = [
            {
                "id": mask_id,
                "label_class_id": label_class_id,
                "geometry_kind": "polygon",
                "points": [
                    {"x": 20, "y": 108},
                    {"x": 38, "y": 72},
                    {"x": 78, "y": 14},
                    {"x": 91, "y": 22},
                    {"x": 58, "y": 76},
                    {"x": 33, "y": 114},
                ],
            }
        ]
    response = client.put(f"/api/v1/images/{image_id}/annotations", json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["image"]["annotation_status"] == "reviewed"
    assert saved["image"]["annotation_revision"] == 1


def test_stabilization_coral_project_imports_snapshots_exports_and_restarts(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Stabilization coral journey")
    project_id = str(project["id"])
    label_class_id = str(project["label_classes"][0]["id"])

    imported = [
        _import_coral_image(
            client,
            project_id,
            filename="swiftia-a.png",
            relative_path="coral-set-a/swiftia-a.png",
            image_format="PNG",
            offset=0,
        ),
        _import_coral_image(
            client,
            project_id,
            filename="swiftia-b.tiff",
            relative_path="coral-set-a/swiftia-b.tiff",
            image_format="TIFF",
            offset=8,
        ),
        _import_coral_image(
            client,
            project_id,
            filename="thesea-c.png",
            relative_path="coral-set-b/thesea-c.png",
            image_format="PNG",
            offset=16,
        ),
    ]
    image_ids = [str(item["image_id"]) for item in imported]
    app = cast(FastAPI, client.app)
    for item, image_id in zip(imported, image_ids, strict=True):
        assert process_thumbnail_job(
            app.state.settings,
            app.state.session_factory,
            str(item["thumbnail_job_id"]),
        )
        image_response = client.get(f"/api/v1/images/{image_id}")
        assert image_response.status_code == 200, image_response.text
        image_payload = image_response.json()
        assert len(str(image_payload["sha256"])) == 64
        assert image_payload["thumbnail_path"]
        content_response = client.get(f"/api/v1/images/{image_id}/content")
        thumbnail_response = client.get(f"/api/v1/images/{image_id}/thumbnail")
        assert content_response.status_code == 200
        assert thumbnail_response.status_code == 200
        assert thumbnail_response.headers["content-type"].startswith("image/jpeg")

    for index, image_id in enumerate(image_ids):
        _save_reviewed_coral_annotation(
            client,
            image_id=image_id,
            label_class_id=label_class_id,
            annotation_id=f"00000000-0000-4000-8000-0000000001{index:02d}",
            mask_id=("00000000-0000-4000-8000-000000000200" if index == 0 else None),
        )
        update_image(
            client,
            image_id,
            group_key="fragment-a" if index < 2 else "fragment-b",
            annotation_status="reviewed",
        )

    version = create_version(client, project_id, name="Stabilization reviewed snapshot")
    version_id = str(version["id"])
    items_response = client.get(f"/api/v1/dataset-versions/{version_id}/items")
    assert items_response.status_code == 200, items_response.text
    items = items_response.json()
    assert len(items) == 3
    splits_by_group: dict[str, set[str]] = {}
    for item in items:
        group = str(item.get("group_key") or item["image_id"])
        splits_by_group.setdefault(group, set()).add(str(item["split"]))
    assert all(len(values) == 1 for values in splits_by_group.values())

    export_response = client.post(
        f"/api/v1/dataset-versions/{version_id}/exports",
        json={"format": "coco_instances"},
    )
    assert export_response.status_code == 200, export_response.text
    export_payload = export_response.json()
    assert process_export_job(
        app.state.settings,
        app.state.session_factory,
        str(export_payload["job"]["id"]),
    )

    archive_path = (
        app.state.settings.resolved_data_dir / export_payload["export"]["archive_path"]
    )
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("export-manifest.json"))
        annotation_files = sorted(
            name
            for name in archive.namelist()
            if name.startswith("annotations/instances_") and name.endswith(".json")
        )
        coco_documents = [json.loads(archive.read(name)) for name in annotation_files]

    assert manifest["format"] == "coco_instances"
    assert manifest["box_annotation_count"] == 3
    assert manifest["mask_annotation_count"] == 1
    assert sum(len(document["images"]) for document in coco_documents) == 3
    assert sum(len(document["annotations"]) for document in coco_documents) == 4
    assert {
        image["reefvision_image_id"]
        for document in coco_documents
        for image in document["images"]
    } == set(image_ids)

    restarted_app = create_app(test_settings)
    with TestClient(restarted_app) as restarted:
        project_response = restarted.get(f"/api/v1/projects/{project_id}")
        assert project_response.status_code == 200, project_response.text
        assert project_response.json()["name"] == "Stabilization coral journey"
        reloaded_items = restarted.get(f"/api/v1/dataset-versions/{version_id}/items")
        assert reloaded_items.status_code == 200, reloaded_items.text
        assert len(reloaded_items.json()) == 3
        annotation_response = restarted.get(f"/api/v1/images/{image_ids[0]}/annotations")
        assert annotation_response.status_code == 200, annotation_response.text
        assert len(annotation_response.json()["annotations"]) == 1
        assert len(annotation_response.json()["mask_annotations"]) == 1
        assert restarted.get(f"/api/v1/images/{image_ids[0]}/thumbnail").status_code == 200
