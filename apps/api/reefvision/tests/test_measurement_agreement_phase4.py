from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project, import_one


def test_measurement_validation_reports_bland_altman_limits(
    client: TestClient,
) -> None:
    project = create_project(client, "Measurement agreement")
    first = import_one(
        client,
        str(project["id"]),
        filename="first.png",
        relative_path="agreement/first.png",
        size=(80, 60),
    )
    second = import_one(
        client,
        str(project["id"]),
        filename="second.png",
        relative_path="agreement/second.png",
        size=(81, 60),
    )
    first_image_id = str(first["successful"][0]["image_id"])
    second_image_id = str(second["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])
    first_mask_id = "406f07b0-e1f2-413a-98c9-13766f4d7c48"
    second_mask_id = "073f35ca-e989-4eae-a72a-132df4e5b384"

    first_saved = client.put(
        f"/api/v1/images/{first_image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": first_mask_id,
                    "label_class_id": label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 10},
                        {"x": 30, "y": 10},
                        {"x": 30, "y": 20},
                        {"x": 10, "y": 20},
                    ],
                }
            ],
        },
    )
    assert first_saved.status_code == 200, first_saved.text
    second_saved = client.put(
        f"/api/v1/images/{second_image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": second_mask_id,
                    "label_class_id": label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 10},
                        {"x": 40, "y": 10},
                        {"x": 40, "y": 20},
                        {"x": 10, "y": 20},
                    ],
                }
            ],
        },
    )
    assert second_saved.status_code == 200, second_saved.text

    response = client.post(
        f"/api/v1/projects/{project['id']}/measurement-validation",
        json={
            "references": [
                {
                    "mask_annotation_id": first_mask_id,
                    "values": [{"metric": "area_pixels", "reference_value": 190}],
                },
                {
                    "mask_annotation_id": second_mask_id,
                    "values": [{"metric": "area_pixels", "reference_value": 280}],
                },
            ]
        },
    )

    assert response.status_code == 200, response.text
    summary = response.json()["summaries"][0]
    expected_standard_deviation = math.sqrt(50)
    assert summary["mean_bias"] == pytest.approx(15)
    assert summary["standard_deviation_bias"] == pytest.approx(expected_standard_deviation)
    assert summary["lower_limit_of_agreement"] == pytest.approx(
        15 - 1.96 * expected_standard_deviation
    )
    assert summary["upper_limit_of_agreement"] == pytest.approx(
        15 + 1.96 * expected_standard_deviation
    )
    assert summary["bias_confidence_interval_lower"] == pytest.approx(
        15 - 1.96 * expected_standard_deviation / math.sqrt(2)
    )
    assert summary["bias_confidence_interval_upper"] == pytest.approx(
        15 + 1.96 * expected_standard_deviation / math.sqrt(2)
    )
    assert summary["pearson_correlation"] == pytest.approx(1)
