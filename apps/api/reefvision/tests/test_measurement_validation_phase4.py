from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_coral_measurements_phase4 import _seed_measurement_image


def test_measurement_reference_comparison_reports_bias_and_tolerance(
    client: TestClient,
) -> None:
    project, image_id, mask_id, _secondary_class_id = _seed_measurement_image(client)
    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 0.1, "unit": "mm", "source": "manual"},
    )
    assert calibrated.status_code == 200, calibrated.text
    profile = client.put(
        f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
        json={
            "base_revision": 1,
            "centerline_points": [{"x": 10, "y": 15}, {"x": 30, "y": 15}],
            "surface_model": "none",
        },
    )
    assert profile.status_code == 200, profile.text

    response = client.post(
        f"/api/v1/projects/{project['id']}/measurement-validation",
        json={
            "default_tolerance_percent": 5,
            "references": [
                {
                    "mask_annotation_id": mask_id,
                    "values": [
                        {"metric": "area_pixels", "reference_value": 200},
                        {
                            "metric": "perimeter_pixels",
                            "reference_value": 63,
                            "tolerance_percent": 10,
                        },
                        {
                            "metric": "total_linear_extension_physical",
                            "reference_value": 2,
                            "unit": "mm",
                        },
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mask_count"] == 1
    assert payload["observation_count"] == 3
    assert payload["passed_count"] == 2
    assert payload["failed_count"] == 1

    observations = {item["metric"]: item for item in payload["observations"]}
    assert observations["area_pixels"]["percent_error"] == pytest.approx(0)
    assert observations["area_pixels"]["passed"] is True
    assert observations["perimeter_pixels"]["signed_error"] == pytest.approx(-3)
    assert observations["perimeter_pixels"]["absolute_error"] == pytest.approx(3)
    assert observations["perimeter_pixels"]["percent_error"] == pytest.approx(
        100 * 3 / 63
    )
    assert observations["perimeter_pixels"]["passed"] is True
    assert observations["total_linear_extension_physical"]["passed"] is True

    perimeter_summary = next(
        item for item in payload["summaries"] if item["metric"] == "perimeter_pixels"
    )
    assert perimeter_summary["mean_bias"] == pytest.approx(-3)
    assert perimeter_summary["mean_absolute_error"] == pytest.approx(3)
    assert perimeter_summary["root_mean_square_error"] == pytest.approx(3)


def test_measurement_validation_skips_unavailable_or_mismatched_units(
    client: TestClient,
) -> None:
    project, _image_id, mask_id, _secondary_class_id = _seed_measurement_image(client)

    response = client.post(
        f"/api/v1/projects/{project['id']}/measurement-validation",
        json={
            "references": [
                {
                    "mask_annotation_id": mask_id,
                    "values": [
                        {
                            "metric": "area_physical",
                            "reference_value": 2,
                            "unit": "mm",
                        },
                        {
                            "metric": "area_pixels",
                            "reference_value": 200,
                            "unit": "cm",
                        },
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["observation_count"] == 0
    assert payload["passed_count"] == 0
    assert payload["failed_count"] == 0
    assert len(payload["warnings"]) == 2
    assert any("unavailable" in warning for warning in payload["warnings"])
    assert any("does not match" in warning for warning in payload["warnings"])
