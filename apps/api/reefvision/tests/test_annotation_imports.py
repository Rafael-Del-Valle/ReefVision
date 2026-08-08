from __future__ import annotations

import json
from io import BytesIO
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models import (
    Annotation,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
)


CLASS_MAPPING = {
    "Swiftia C": {
        "id": "94d097d4-cc0c-4695-8670-2ade36cc6993",
        "short_label_code": "Swiftia C",
        "long_label_code": "Swiftia Closed",
        "color": [136, 91, 0, 255],
    },
    "Swiftia O": {
        "id": "93b1b400-7ef4-4a30-810f-ebaba306cdc9",
        "short_label_code": "Swiftia O",
        "long_label_code": "Swiftia Open",
        "color": [255, 170, 0, 255],
    },
    "Muricea O": {
        "id": "cdd8ac00-a5e9-489b-9b8a-c3f0275fe88c",
        "short_label_code": "Muricea O",
        "long_label_code": "Muricea Open",
        "color": [255, 255, 255, 255],
    },
    "Thesea C": {
        "id": "26731a4e-6004-4175-b4fa-a9e052c73008",
        "short_label_code": "Thesea C",
        "long_label_code": "Thesea Closed",
        "color": [131, 0, 131, 255],
    },
}

DATA_YAML = """names:
  0: Muricea C
  1: Thesea C
  2: Muricea O
  3: Swiftia O
  4: Thesea O
  5: Swiftia C
nc: 6
"""


def image_bytes(size: tuple[int, int] = (100, 80)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (20, 90, 120)).save(stream, format="PNG")
    return stream.getvalue()


def create_project(client: TestClient, template: str = "octocoral") -> dict[str, Any]:
    response = client.post(
        "/api/v1/projects",
        json={"name": f"Import {template}", "template": template},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def import_image(client: TestClient, project_id: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[("files", ("coral.png", image_bytes(), "image/png"))],
        data={"relative_paths": "trial-1/coral.png"},
    )
    assert response.status_code == 200, response.text
    return cast(str, response.json()["successful"][0]["image_id"])


def annotation_payload() -> dict[str, list[dict[str, Any]]]:
    return {
        r"C:\old-project\trial-1\coral.png": [
            {
                "id": "rectangle-1",
                "type": "RectangleAnnotation",
                "label_short_code": "Swiftia C",
                "label_long_code": "Swiftia Closed",
                "label_id": CLASS_MAPPING["Swiftia C"]["id"],
                "annotation_color": [136, 91, 0, 255],
                "image_path": r"C:\old-project\trial-1\coral.png",
                "top_left": [10, 8],
                "bottom_right": [30, 28],
                "verified": True,
            },
            {
                "id": "patch-1",
                "type": "PatchAnnotation",
                "label_short_code": "Thesea C",
                "label_long_code": "Thesea Closed",
                "label_id": CLASS_MAPPING["Thesea C"]["id"],
                "annotation_color": [131, 0, 131, 255],
                "image_path": r"C:\old-project\trial-1\coral.png",
                "center_xy": [60, 30],
                "annotation_size": 20,
                "verified": True,
            },
            {
                "id": "polygon-1",
                "type": "PolygonAnnotation",
                "label_short_code": "Muricea O",
                "label_long_code": "Muricea Open",
                "label_id": CLASS_MAPPING["Muricea O"]["id"],
                "annotation_color": [255, 255, 255, 255],
                "image_path": r"C:\old-project\trial-1\coral.png",
                "points": [[40, 45], [55, 45], [55, 60], [40, 60]],
                "holes": [],
                "verified": True,
            },
            {
                "id": "multipolygon-1",
                "type": "MultiPolygonAnnotation",
                "label_short_code": "Swiftia O",
                "label_long_code": "Swiftia Open",
                "label_id": CLASS_MAPPING["Swiftia O"]["id"],
                "annotation_color": [255, 170, 0, 255],
                "image_path": r"C:\old-project\trial-1\coral.png",
                "verified": True,
                "polygons": [
                    {
                        "points": [[5, 45], [15, 45], [15, 55], [5, 55]],
                        "holes": [],
                    },
                    {
                        "points": [[20, 45], [30, 45], [30, 55], [20, 55]],
                        "holes": [],
                    },
                ],
            },
        ]
    }


def import_annotations(client: TestClient, project_id: str):
    return client.post(
        f"/api/v1/projects/{project_id}/imports/annotations",
        files=[
            (
                "files",
                (
                    "annotations.json",
                    json.dumps(annotation_payload()),
                    "application/json",
                ),
            ),
            (
                "files",
                ("class_mapping.json", json.dumps(CLASS_MAPPING), "application/json"),
            ),
            ("files", ("data.yaml", DATA_YAML, "application/yaml")),
        ],
    )


def test_coralnet_toolbox_import_creates_native_boxes_and_masks(client: TestClient) -> None:
    project = create_project(client)
    image_id = import_image(client, project["id"])

    response = import_annotations(client, project["id"])

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["annotation_files"] == 1
    assert report["class_mapping_files"] == 1
    assert report["dataset_yaml_files"] == 1
    assert report["boxes_imported"] == 2
    assert report["masks_imported"] == 3
    assert report["duplicate_annotations"] == 0
    assert report["skipped_annotations"] == 0
    assert report["classes_created"] == 0

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        boxes = session.query(Annotation).filter_by(image_id=image_id).all()
        masks = session.query(MaskAnnotation).filter_by(image_id=image_id).all()
        image = session.get(ImageAsset, image_id)

        assert len(boxes) == 2
        assert len(masks) == 3
        assert image is not None
        assert image.annotation_revision == 1
        assert image.annotation_status == "annotated"
        assert all(item.source_type == "imported" for item in boxes)
        assert all(item.source_type == "imported" for item in masks)
        assert boxes[0].provenance_json is not None
        assert boxes[0].provenance_json["import_format"] == "coralnet_toolbox"
        assert any(
            mask.provenance_json
            and mask.provenance_json.get("external_multipolygon_part") == 1
            for mask in masks
        )

    repeat = import_annotations(client, project["id"])
    assert repeat.status_code == 200, repeat.text
    repeated_report = repeat.json()
    assert repeated_report["boxes_imported"] == 0
    assert repeated_report["masks_imported"] == 0
    assert repeated_report["duplicate_annotations"] == 5

    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        assert image.annotation_revision == 1


def test_import_can_create_missing_class_without_reindexing_existing_classes(
    client: TestClient,
) -> None:
    project = create_project(client, template="blank")
    image_id = import_image(client, project["id"])
    payload = {
        "coral.png": [
            {
                "id": "new-class-box",
                "type": "RectangleAnnotation",
                "label_short_code": "Swiftia C",
                "label_long_code": "Swiftia Closed",
                "label_id": CLASS_MAPPING["Swiftia C"]["id"],
                "annotation_color": [136, 91, 0, 255],
                "image_path": "coral.png",
                "top_left": [1, 1],
                "bottom_right": [12, 12],
                "verified": True,
            }
        ]
    }

    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/annotations",
        files=[
            ("files", ("annotations.json", json.dumps(payload), "application/json")),
            (
                "files",
                ("class_mapping.json", json.dumps(CLASS_MAPPING), "application/json"),
            ),
            ("files", ("data.yaml", DATA_YAML, "application/yaml")),
        ],
    )

    assert response.status_code == 200, response.text
    assert response.json()["classes_created"] == 1
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        created = (
            session.query(LabelClass)
            .filter_by(project_id=project["id"], name="Swiftia Closed")
            .one()
        )
        assert created.class_index == 5
        assert created.display_color == "#885B00"
        assert session.query(Annotation).filter_by(image_id=image_id).count() == 1


def test_polygon_holes_are_reported_instead_of_silently_discarded(
    client: TestClient,
) -> None:
    project = create_project(client)
    import_image(client, project["id"])
    payload = {
        "coral.png": [
            {
                "id": "polygon-with-hole",
                "type": "PolygonAnnotation",
                "label_short_code": "Muricea O",
                "label_long_code": "Muricea Open",
                "label_id": CLASS_MAPPING["Muricea O"]["id"],
                "image_path": "coral.png",
                "points": [[5, 5], [40, 5], [40, 40], [5, 40]],
                "holes": [[[15, 15], [20, 15], [20, 20], [15, 20]]],
                "verified": True,
            }
        ]
    }

    response = client.post(
        f"/api/v1/projects/{project['id']}/imports/annotations",
        files=[("files", ("annotations.json", json.dumps(payload), "application/json"))],
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["masks_imported"] == 0
    assert report["skipped_annotations"] == 1
    assert "cannot preserve" in report["issues"][0]["detail"]
