from __future__ import annotations

import json
import zipfile

from fastapi.testclient import TestClient

from reefvision.services.coco_rle import decode_compact_counts, encode_compact_counts
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


def test_compact_coco_rle_codec_matches_reference_delta_rules() -> None:
    counts = [7, 3, 2, 6, 4, 9, 1, 8]
    encoded = encode_compact_counts(counts)
    assert isinstance(encoded, str)
    assert decode_compact_counts(encoded) == counts


def test_interchange_round_trips_compact_coco_rle(client: TestClient) -> None:
    project = create_project(client, "Compact COCO RLE")
    project_id = str(project["id"])
    imported = import_one(client, project_id)
    image_id = str(imported["successful"][0]["image_id"])
    image_response = client.get(f"/api/v1/images/{image_id}")
    assert image_response.status_code == 200, image_response.text
    filename = str(image_response.json()["original_filename"])
    project_detail = client.get(f"/api/v1/projects/{project_id}")
    assert project_detail.status_code == 200, project_detail.text
    label_class = project_detail.json()["label_classes"][0]

    # The managed test image is 80x60. Its first column has five foreground pixels.
    counts = [0, 5, 4_795]
    compact = encode_compact_counts(counts)
    document = {
        "images": [
            {
                "id": 1,
                "file_name": filename,
                "width": 80,
                "height": 60,
                "reefvision_image_id": image_id,
            }
        ],
        "categories": [{"id": 1, "name": label_class["name"]}],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "segmentation": {"size": [60, 80], "counts": compact},
                "iscrowd": 1,
            }
        ],
    }
    preview = client.post(
        f"/api/v1/projects/{project_id}/interchange/preview",
        json={
            "format": "coco_instance",
            "document": document,
            "class_mapping": {"1": label_class["id"]},
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["valid"] is True
    assert payload["source_annotation_count"] == 1
    assert payload["importable_mask_count"] == 1

    applied = client.post(
        f"/api/v1/projects/{project_id}/interchange/apply",
        json={
            "format": "coco_instance",
            "document": document,
            "class_mapping": {"1": label_class["id"]},
            "preview_checksum": payload["preview_checksum"],
        },
    )
    assert applied.status_code == 201, applied.text
    assert len(applied.json()["created_mask_annotation_ids"]) == 1

    exported = client.post(
        f"/api/v1/projects/{project_id}/interchange/export",
        json={
            "format": "coco_instance",
            "include_images": False,
            "include_boxes": False,
            "include_masks": True,
            "coco_rle_encoding": "compressed",
        },
    )
    assert exported.status_code == 201, exported.text
    result = exported.json()
    assert any("compact COCO RLE" in warning for warning in result["warnings"])
    archive_path = resolve_managed_project_path(
        client.app.state.settings,
        result["archive_path"],
    )
    with zipfile.ZipFile(archive_path) as archive:
        document_out = json.loads(archive.read("annotations.json"))
        manifest = json.loads(archive.read("reefvision-manifest.json"))
    segmentation = document_out["annotations"][0]["segmentation"]
    assert segmentation["size"] == [60, 80]
    assert isinstance(segmentation["counts"], str)
    assert decode_compact_counts(segmentation["counts"]) == counts
    assert document_out["annotations"][0]["iscrowd"] == 1
    assert manifest["coco_rle_encoding"] == "compressed"
    assert manifest["compressed_rle_mask_count"] == 1
