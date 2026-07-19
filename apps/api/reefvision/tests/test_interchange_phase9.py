from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.db.models import Annotation, ImageAsset, LabelClass, MaskAnnotation
from reefvision.storage.projects import resolve_managed_project_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_project_image(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/v1/projects",
        json={"name": "Interchange project", "template": "blank"},
    )
    assert created.status_code == 201
    project = created.json()
    image_id = "11111111-1111-4111-8111-111111111111"
    relative = f"{project['storage_root']}/images/coral.png"
    path = resolve_managed_project_path(client.app.state.settings, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 80), (12, 34, 56)).save(path)
    with client.app.state.session_factory() as session:
        session.add(
            LabelClass(
                project_id=project["id"],
                class_index=0,
                display_order=0,
                name="Coral",
                display_color="#57CC99",
                is_active=True,
            )
        )
        session.add(
            ImageAsset(
                id=image_id,
                project_id=project["id"],
                original_filename="coral.png",
                managed_path=relative,
                thumbnail_path=None,
                sha256=_sha256(path),
                width_px=100,
                height_px=80,
                file_size_bytes=path.stat().st_size,
                media_type="image/png",
                import_source="test",
                metadata_json={},
                annotation_status="unannotated",
                annotation_revision=0,
            )
        )
        session.commit()
    return project["id"], image_id


def test_labelme_preview_apply_and_coco_export(client: TestClient) -> None:
    project_id, image_id = _seed_project_image(client)
    request = {
        "format": "labelme",
        "document": {
            "imagePath": "coral.png",
            "imageWidth": 100,
            "imageHeight": 80,
            "shapes": [
                {
                    "label": "Coral",
                    "shape_type": "rectangle",
                    "points": [[10, 12], [30, 42]],
                },
                {
                    "label": "Coral",
                    "shape_type": "polygon",
                    "points": [[50, 10], [75, 20], [60, 55]],
                },
            ],
        },
        "existing_annotation_policy": "append",
    }
    preview = client.post(
        f"/api/v1/projects/{project_id}/interchange/preview",
        json=request,
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["valid"] is True
    assert preview_payload["matched_image_count"] == 1
    assert preview_payload["matched_category_count"] == 1
    assert preview_payload["importable_box_count"] == 1
    assert preview_payload["importable_mask_count"] == 1

    applied = client.post(
        f"/api/v1/projects/{project_id}/interchange/apply",
        json={**request, "preview_checksum": preview_payload["preview_checksum"]},
    )
    assert applied.status_code == 201
    assert len(applied.json()["created_annotation_ids"]) == 1
    assert len(applied.json()["created_mask_annotation_ids"]) == 1

    with client.app.state.session_factory() as session:
        assert (
            len(list(session.scalars(select(Annotation).where(Annotation.image_id == image_id))))
            == 1
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(MaskAnnotation).where(MaskAnnotation.image_id == image_id)
                    )
                )
            )
            == 1
        )

    exported = client.post(
        f"/api/v1/projects/{project_id}/interchange/export",
        json={
            "format": "coco_instance",
            "include_images": True,
            "include_boxes": True,
            "include_masks": True,
        },
    )
    assert exported.status_code == 201
    export_payload = exported.json()
    assert export_payload["image_count"] == 1
    assert export_payload["box_annotation_count"] == 1
    assert export_payload["mask_annotation_count"] == 1
    archive = resolve_managed_project_path(
        client.app.state.settings,
        export_payload["archive_path"],
    )
    assert archive.is_file()
    assert _sha256(archive) == export_payload["archive_sha256"]


def test_interchange_rejects_stale_preview(client: TestClient) -> None:
    project_id, _image_id = _seed_project_image(client)
    request = {
        "format": "labelme",
        "document": {
            "imagePath": "coral.png",
            "imageWidth": 100,
            "imageHeight": 80,
            "shapes": [],
        },
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/interchange/apply",
        json={**request, "preview_checksum": "0" * 64},
    )
    assert response.status_code == 409
