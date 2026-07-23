from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.services.coco_rle import decode_compact_counts, encode_compact_counts
from reefvision.tests.test_annotations import create_project, import_one


def test_compact_coco_rle_codec_matches_reference_delta_rules() -> None:
    counts = [7, 3, 2, 6, 4, 9, 1, 8]
    encoded = encode_compact_counts(counts)
    assert isinstance(encoded, str)
    assert decode_compact_counts(encoded) == counts


def test_interchange_preview_accepts_compact_coco_rle(client: TestClient) -> None:
    project = create_project(client, "Compact COCO RLE")
    project_id = str(project["id"])
    imported = import_one(client, project_id)
    image = imported["successful"][0]
    image_id = str(image["image_id"])
    filename = str(image["original_filename"])
    project_detail = client.get(f"/api/v1/projects/{project_id}")
    assert project_detail.status_code == 200, project_detail.text
    label_class = project_detail.json()["label_classes"][0]

    # 10x10 Fortran-order raster: first column has five foreground pixels.
    counts = [0, 5, 95]
    compact = encode_compact_counts(counts)
    document = {
        "images": [
            {
                "id": 1,
                "file_name": filename,
                "width": 10,
                "height": 10,
                "reefvision_image_id": image_id,
            }
        ],
        "categories": [{"id": 1, "name": label_class["name"]}],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "segmentation": {"size": [10, 10], "counts": compact},
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
