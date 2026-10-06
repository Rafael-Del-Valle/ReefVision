from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.jobs.export import process_export_job
from reefvision.main import create_app
from reefvision.tests.class_fixtures import seed_synthetic_label_classes

MURICEA_OPEN_ID = "cdd8ac00-a5e9-489b-9b8a-c3f0275fe88c"


def _image_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (100, 80), (20, 90, 120)).save(stream, format="PNG")
    return stream.getvalue()


def _project_and_image(client: TestClient) -> tuple[dict[str, Any], str]:
    project_response = client.post(
        "/api/v1/projects",
        json={
            "name": "Milestone 2 native import acceptance",
            "template": "blank",
        },
    )
    assert project_response.status_code == 201, project_response.text

    project = seed_synthetic_label_classes(
        client,
        cast(dict[str, Any], project_response.json()),
    )

    image_response = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("coral.png", _image_bytes(), "image/png"))],
        data={"relative_paths": "trial/coral.png"},
    )
    assert image_response.status_code == 200, image_response.text
    image_id = cast(str, image_response.json()["successful"][0]["image_id"])
    return project, image_id


def _import_polygon(client: TestClient, project_id: str) -> None:
    payload = {
        "coral.png": [
            {
                "id": "native-workflow-polygon",
                "type": "PolygonAnnotation",
                "label_short_code": "Muricea O",
                "label_long_code": "Muricea Open",
                "label_id": MURICEA_OPEN_ID,
                "annotation_color": [255, 255, 255, 255],
                "image_path": "coral.png",
                "points": [[20, 20], [50, 20], [50, 50], [20, 50]],
                "holes": [],
                "verified": True,
            }
        ]
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/annotations",
        files=[("files", ("annotations.json", json.dumps(payload), "application/json"))],
    )
    assert response.status_code == 200, response.text
    assert response.json()["masks_imported"] == 1


def test_imported_polygon_is_editable_measurable_freezable_exportable_and_restart_safe(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project, image_id = _project_and_image(client)
    _import_polygon(client, project["id"])

    session_response = client.get(f"/api/v1/images/{image_id}/annotations")
    assert session_response.status_code == 200, session_response.text
    annotation_session = session_response.json()
    assert len(annotation_session["mask_annotations"]) == 1
    imported_mask = annotation_session["mask_annotations"][0]
    assert imported_mask["geometry_kind"] == "polygon"
    assert imported_mask["source_type"] == "imported"
    mask_id = imported_mask["id"]

    measured = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert measured.status_code == 200, measured.text
    assert measured.json()["area_pixels"] == 900
    assert measured.json()["perimeter_pixels"] == 120.0

    thesea_open = next(
        item for item in annotation_session["label_classes"] if item["name"] == "Thesea Open"
    )
    save_response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": annotation_session["image"]["annotation_revision"],
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": thesea_open["id"],
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 20, "y": 20},
                        {"x": 55, "y": 20},
                        {"x": 55, "y": 50},
                        {"x": 20, "y": 50},
                    ],
                }
            ],
            "deleted_mask_annotation_ids": [],
        },
    )
    assert save_response.status_code == 200, save_response.text
    edited = save_response.json()["mask_annotations"][0]
    assert edited["id"] == mask_id
    assert edited["label_class_id"] == thesea_open["id"]
    assert edited["revision"] == 2
    assert edited["source_type"] == "imported"

    measured_after_edit = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert measured_after_edit.status_code == 200
    assert measured_after_edit.json()["area_pixels"] == 1050

    version_response = client.post(
        f"/api/v1/projects/{project['id']}/dataset-versions",
        json={
            "name": "Imported mask acceptance snapshot",
            "eligible_annotation_statuses": ["reviewed"],
            "split_method": "none",
            "reuse_parent_assignments": False,
            "manual_assignments": [],
        },
    )
    assert version_response.status_code == 201, version_response.text
    version = version_response.json()
    assert version["mask_annotation_count"] == 1
    assert version["schema_version"] == "0007"

    items_response = client.get(f"/api/v1/dataset-versions/{version['id']}/items")
    assert items_response.status_code == 200, items_response.text
    items = items_response.json()
    assert len(items) == 1
    assert items[0]["mask_annotation_count"] == 1
    frozen_mask = items[0]["mask_annotation_snapshot_json"][0]
    assert frozen_mask["id"] == mask_id
    assert frozen_mask["revision"] == 2
    assert frozen_mask["source_type"] == "imported"
    assert frozen_mask["class_name"] == "Thesea Open"

    export_response = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={"format": "semantic_masks"},
    )
    assert export_response.status_code == 200, export_response.text
    export_job = export_response.json()["job"]

    app = cast(FastAPI, client.app)
    assert process_export_job(app.state.settings, app.state.session_factory, export_job["id"])

    export_id = export_response.json()["export"]["id"]
    completed_export = client.get(f"/api/v1/exports/{export_id}")
    assert completed_export.status_code == 200
    assert completed_export.json()["status"] == "succeeded"
    archive = client.get(f"/api/v1/exports/{export_id}/download")
    assert archive.status_code == 200
    with zipfile.ZipFile(BytesIO(archive.content)) as zipped:
        names = set(zipped.namelist())
        assert "classes.json" in names
        assert "dataset-version-manifest.json" in names
        assert any(name.startswith("masks/") and name.endswith(".png") for name in names)

    # Restart a second application instance against the same managed data/database.
    restart_app = create_app(test_settings)
    with TestClient(restart_app) as restarted:
        restarted_session = restarted.get(f"/api/v1/images/{image_id}/annotations")
        assert restarted_session.status_code == 200, restarted_session.text
        persisted = restarted_session.json()["mask_annotations"]
        assert len(persisted) == 1
        assert persisted[0]["id"] == mask_id
        assert persisted[0]["revision"] == 2
        assert persisted[0]["label_class_id"] == thesea_open["id"]
