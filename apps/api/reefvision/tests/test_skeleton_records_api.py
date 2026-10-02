from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def _seed_mask(client: TestClient) -> str:
    project = create_project(client, "Skeleton records API")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "34d16721-407e-41c4-ae9a-698281893cf1"

    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 20},
                        {"x": 60, "y": 20},
                        {"x": 60, "y": 30},
                        {"x": 10, "y": 30},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return mask_id


def test_skeleton_record_api_create_correct_review_export_download(
    client: TestClient,
) -> None:
    mask_id = _seed_mask(client)

    created_response = client.post(
        f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses",
        json={"terminal_spur_max_length_pixels": 0},
    )
    assert created_response.status_code == 200, created_response.text
    automatic = created_response.json()
    assert automatic["analysis_revision"] == 1
    assert automatic["source_kind"] == "automatic"
    assert automatic["review_status"] == "unreviewed"
    assert automatic["result"]["final_skeleton_source"] == "automatic_pruned"

    history_response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses"
    )
    assert history_response.status_code == 200, history_response.text
    assert [item["id"] for item in history_response.json()] == [
        automatic["id"]
    ]

    endpoint = min(
        automatic["result"]["final_skeleton_pixels"],
        key=lambda point: (point["x"], point["y"]),
    )
    assert endpoint["x"] > 0
    correction_response = client.post(
        f"/api/v1/skeleton-analyses/{automatic['id']}/corrections",
        json={
            "add_pixels": [
                {
                    "x": endpoint["x"] - 1,
                    "y": endpoint["y"],
                }
            ],
            "remove_pixels": [],
            "reason_code": "extend_endpoint",
            "note": "Reviewer extended the visible centerline.",
        },
    )
    assert correction_response.status_code == 200, correction_response.text
    corrected = correction_response.json()
    assert corrected["analysis_revision"] == 2
    assert corrected["supersedes_analysis_id"] == automatic["id"]
    assert corrected["source_kind"] == "human_corrected"
    assert corrected["result"]["final_skeleton_source"] == "human_corrected"
    assert corrected["result"]["human_correction_applied"] is True

    review_response = client.post(
        f"/api/v1/skeleton-analyses/{corrected['id']}/review",
        json={
            "review_status": "approved",
            "note": "Topology and centerline checked against source image.",
        },
    )
    assert review_response.status_code == 200, review_response.text
    approved = review_response.json()
    assert approved["review_status"] == "approved"
    assert approved["reviewed_at"] is not None

    final_history = client.get(
        f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses"
    )
    assert final_history.status_code == 200, final_history.text
    revisions = final_history.json()
    assert [item["analysis_revision"] for item in revisions] == [1, 2]
    assert revisions[0]["result"]["final_skeleton_source"] == "automatic_pruned"
    assert revisions[1]["result"]["final_skeleton_source"] == "human_corrected"

    export_response = client.post(
        f"/api/v1/skeleton-analyses/{corrected['id']}/export"
    )
    assert export_response.status_code == 200, export_response.text
    exported = export_response.json()
    assert exported["verification_status"] == "verified"
    assert exported["analysis_revision"] == 2

    download = client.get(
        f"/api/v1/skeleton-analyses/{corrected['id']}/export/download"
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = set(archive.namelist())
        prefix = f"{exported['package_name']}/"
        assert prefix + "data/analysis.json" in names
        assert prefix + "data/provenance.json" in names
        assert prefix + "data/final_skeleton_pixels.csv" in names
        assert prefix + "manifest.json" in names
        assert prefix + "checksums.sha256" in names
