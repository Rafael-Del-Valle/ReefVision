from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def _seed_bar_mask(client: TestClient) -> tuple[str, str]:
    project = create_project(client, "Skeleton measurement calibration")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "95ee190a-7f58-4ef6-a8ab-81d93c61f3d3"

    saved = client.put(
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
    assert saved.status_code == 200, saved.text
    return image_id, mask_id


def test_structure_analysis_reports_pixel_and_scalar_calibrated_tle(
    client: TestClient,
) -> None:
    image_id, mask_id = _seed_bar_mask(client)

    pixel_response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/structure-analysis"
    )
    assert pixel_response.status_code == 200, pixel_response.text
    pixel = pixel_response.json()
    assert pixel["calibrated"] is False
    assert pixel["length_calibration_method"] == "pixel_only"
    assert pixel["physical_unit"] is None
    assert pixel["raw_branch_count"] == 1
    assert pixel["pruned_branch_count"] == 1
    assert pixel["raw_total_linear_extension_pixels"] > 0
    assert pixel["pruned_total_linear_extension_pixels"] == pytest.approx(
        pixel["raw_total_linear_extension_pixels"]
    )
    assert pixel["raw_longest_path_pixels"] == pytest.approx(
        pixel["raw_total_linear_extension_pixels"]
    )
    assert pixel["raw_total_linear_extension_physical"] is None
    assert pixel["raw_longest_path_physical"] is None
    assert pixel["raw_branch_angles"] == []
    assert pixel["branch_angle_space"] == "image_pixels"

    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.25,
            "unit": "mm",
            "source": "manual_scale_bar",
            "confidence": 1.0,
        },
    )
    assert calibrated.status_code == 200, calibrated.text

    scalar_response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/structure-analysis"
    )
    assert scalar_response.status_code == 200, scalar_response.text
    scalar = scalar_response.json()
    assert scalar["calibrated"] is True
    assert scalar["physical_unit"] == "mm"
    assert scalar["distance_per_pixel"] == pytest.approx(0.25)
    assert scalar["calibration_source"] == "manual_scale_bar"
    assert scalar["calibration_confidence"] == pytest.approx(1.0)
    assert scalar["perspective_corrected"] is False
    assert scalar["length_calibration_method"] == "scalar_distance_per_pixel"
    assert scalar["raw_total_linear_extension_physical"] == pytest.approx(
        scalar["raw_total_linear_extension_pixels"] * 0.25
    )
    assert scalar["raw_longest_path_physical"] == pytest.approx(
        scalar["raw_longest_path_pixels"] * 0.25
    )
    assert scalar["graph_edges"][0]["length_physical"] == pytest.approx(
        scalar["graph_edges"][0]["node_to_node_length_pixels"] * 0.25
    )


def test_reference_plane_homography_controls_skeleton_length_calibration(
    client: TestClient,
) -> None:
    image_id, mask_id = _seed_bar_mask(client)

    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.25,
            "unit": "cm",
            "source": "aruco",
            "confidence": 0.95,
            "perspective_homography": [
                [0.5, 0.0, 0.0],
                [0.0, 0.5, 0.0],
                [0.0, 0.0, 1.0],
            ],
            "reference_plane_only": True,
        },
    )
    assert calibrated.status_code == 200, calibrated.text

    response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/structure-analysis"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["calibrated"] is True
    assert payload["physical_unit"] == "cm"
    assert payload["perspective_corrected"] is True
    assert payload["reference_plane_only"] is True
    assert payload["length_calibration_method"] == "reference_plane_homography"
    assert payload["branch_angle_space"] == "reference_plane"
    assert payload["raw_total_linear_extension_physical"] == pytest.approx(
        payload["raw_total_linear_extension_pixels"] * 0.5
    )
    assert payload["raw_longest_path_physical"] == pytest.approx(
        payload["raw_longest_path_pixels"] * 0.5
    )
