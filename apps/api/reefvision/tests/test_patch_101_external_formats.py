"""Patch 1.0.1: supported external annotation imports preserve semantic classes."""

from __future__ import annotations

import json
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Annotation, LabelClass, MaskAnnotation
from reefvision.tests.test_annotations import create_project, import_one


def test_coco_json_preserves_categories_annotations_and_unreferenced_labels(
    client: TestClient,
) -> None:
    project = create_project(client, "COCO preserved labels")
    report = import_one(client, project["id"], filename="coco.png")
    image_id = report["successful"][0]["image_id"]
    coco = {
        "images": [{"id": 23, "file_name": "coco.png", "height": 60, "width": 80}],
        "categories": [
            {"id": 42, "name": "Swiftia exserta"},
            {"id": 99, "name": "Muricea pendula"},
        ],
        "annotations": [
            {"id": 1, "image_id": 23, "category_id": 42, "bbox": [5, 5, 20, 15]},
            {
                "id": 2,
                "image_id": 23,
                "category_id": 42,
                "segmentation": [[12, 12, 18, 12, 18, 20, 12, 20]],
            },
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/annotations",
        files=[("files", ("annotations_coco.json", json.dumps(coco), "application/json"))],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["boxes_imported"] == 1
    assert payload["masks_imported"] == 1

    with cast(FastAPI, client.app).state.session_factory() as session:
        labels = list(
            session.scalars(select(LabelClass).where(LabelClass.project_id == project["id"]))
        )
        expected = {c.name: c.id for c in labels}
        assert "Swiftia exserta" in expected
        assert "Muricea pendula" in expected  # class without any annotation
        annotations = list(
            session.scalars(select(Annotation).where(Annotation.image_id == image_id))
        )
        masks = list(
            session.scalars(select(MaskAnnotation).where(MaskAnnotation.image_id == image_id))
        )
        assert len(annotations) == len(masks) == 1
        assert annotations[0].label_class_id == expected["Swiftia exserta"]
        assert masks[0].label_class_id == expected["Swiftia exserta"]
        assert masks[0].status == "needs_review"

    repeat = client.post(
        f"/api/v1/projects/{project['id']}/imports/annotations",
        files=[("files", ("annotations_coco.json", json.dumps(coco), "application/json"))],
    )
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["boxes_imported"] == 0
    assert repeat.json()["masks_imported"] == 0


def test_coco_uncompressed_rle_remains_editable_mask(
    client: TestClient,
) -> None:
    project = create_project(client, "COCO raster labels")
    report = import_one(client, project["id"], filename="rle.png")
    image_id = report["successful"][0]["image_id"]
    coco = {
        "images": [{"id": 1, "file_name": "rle.png", "height": 60, "width": 80}],
        "categories": [{"id": 2, "name": "Thesea nivea"}],
        "annotations": [
            {
                "id": 4,
                "image_id": 1,
                "category_id": 2,
                "segmentation": {"size": [60, 80], "counts": [0, 10, 4790]},
            }
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/annotations",
        files=[("files", ("rle_annotations.json", json.dumps(coco), "application/json"))],
    )
    assert response.status_code == 200, response.text
    assert response.json()["masks_imported"] == 1
    with cast(FastAPI, client.app).state.session_factory() as session:
        masks = list(
            session.scalars(select(MaskAnnotation).where(MaskAnnotation.image_id == image_id))
        )
        assert len(masks) == 1
        assert masks[0].area_pixels == 10
        assert masks[0].status == "needs_review"
        assert masks[0].provenance_json["external_format"] == "coco"


def test_yolo_data_yaml_and_labels_transfer_all_class_names(
    client: TestClient,
) -> None:
    project = create_project(client, "YOLO labels")
    report = import_one(client, project["id"], filename="yolo.png")
    image_id = report["successful"][0]["image_id"]
    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/annotations",
        files=[
            ("files", ("yolo.txt", "0 0.5 0.5 0.25 0.5\n", "text/plain")),
            ("files", ("data.yaml", "names:\n  0: 'Jellyfish'\n  1: 'Octocoral'\n", "text/yaml")),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["boxes_imported"] == 1
    with cast(FastAPI, client.app).state.session_factory() as session:
        labels = list(
            session.scalars(select(LabelClass).where(LabelClass.project_id == project["id"]))
        )
        classes = {c.name: c.id for c in labels}
        assert "Jellyfish" in classes
        assert "Octocoral" in classes
        boxes = list(session.scalars(select(Annotation).where(Annotation.image_id == image_id)))
        assert len(boxes) == 1
        assert boxes[0].label_class_id == classes["Jellyfish"]
        assert boxes[0].x_min == 30
        assert boxes[0].x_max == 50
        assert boxes[0].y_min == 15
        assert boxes[0].y_max == 45
