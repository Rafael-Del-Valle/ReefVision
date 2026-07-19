from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def test_scientific_validation_accepts_frozen_predicted_values(
    client: TestClient,
) -> None:
    project = create_project(client, "Scientific validation")
    response = client.post(
        f"/api/v1/projects/{project['id']}/scientific-validation",
        json={
            "dataset_name": "Frozen coral references",
            "dataset_version": "v1",
            "observations": [
                {
                    "specimen_id": "coral-1",
                    "metric": "area_pixels",
                    "reference_value": 100.0,
                    "predicted_value": 101.0,
                    "unit": "pixels",
                    "observer_id": "observer-a",
                },
                {
                    "specimen_id": "coral-2",
                    "metric": "area_pixels",
                    "reference_value": 200.0,
                    "predicted_value": 198.0,
                    "unit": "pixels",
                    "observer_id": "observer-a",
                },
                {
                    "specimen_id": "coral-1",
                    "metric": "area_pixels",
                    "reference_value": 102.0,
                    "predicted_value": 101.0,
                    "unit": "pixels",
                    "observer_id": "observer-b",
                },
                {
                    "specimen_id": "coral-2",
                    "metric": "area_pixels",
                    "reference_value": 198.0,
                    "predicted_value": 198.0,
                    "unit": "pixels",
                    "observer_id": "observer-b",
                },
            ],
            "thresholds": {
                "area_pixels": {
                    "maximum_mae": 2.0,
                    "maximum_rmse": 2.0,
                    "maximum_absolute_bias": 1.0,
                    "minimum_sample_count": 4,
                }
            },
            "persist_report": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["passed"] is True
    assert len(payload["frozen_dataset_checksum"]) == 64
    assert len(payload["report_checksum"]) == 64
    assert payload["metric_results"][0]["sample_count"] == 4
    assert payload["metric_results"][0]["passed"] is True
    assert payload["artifact_id"] is None
