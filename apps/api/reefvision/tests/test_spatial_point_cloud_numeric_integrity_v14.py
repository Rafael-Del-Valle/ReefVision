"""Reject silent numeric coercion in provisional 3D point-cloud science."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

PARAMS: dict[str, Any] = {
    "points": [[0, 0, 0], [3, 4, 0]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified field ruler",
    "relative_scale_uncertainty": 0.1,
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("meters_per_unit", "0.01"),
        ("relative_scale_uncertainty", False),
        ("relative_scale_uncertainty", "0.1"),
        ("points", [[True, 0, 0], [3, 4, 0]]),
        ("points", [["0", 0, 0], [3, 4, 0]]),
    ],
)
def test_schema_rejects_coerced_scientific_numbers(field: str, value: object) -> None:
    with pytest.raises(PydanticValidationError):
        PointCloudPreviewRequest.model_validate({**PARAMS, field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("meters_per_unit", "0.01"),
        ("relative_scale_uncertainty", False),
        ("relative_scale_uncertainty", "0.1"),
        ("points", [[True, 0, 0], [3, 4, 0]]),
        ("points", [["0", 0, 0], [3, 4, 0]]),
    ],
)
def test_direct_service_rejects_coerced_scientific_numbers(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        measure_point_cloud_preview(**{**PARAMS, field: value})


def test_numeric_integer_coordinates_and_zero_uncertainty_remain_valid() -> None:
    request = PointCloudPreviewRequest.model_validate(
        {**PARAMS, "meters_per_unit": 1, "relative_scale_uncertainty": 0}
    )
    result = measure_point_cloud_preview(
        points=request.points,
        meters_per_unit=request.meters_per_unit,
        calibration_method=request.calibration_method,
        calibration_evidence=request.calibration_evidence,
        relative_scale_uncertainty=request.relative_scale_uncertainty,
    )
    assert result["selected_point_chords"] == []
    assert result["axis_aligned_dimensions_m"] == [3.0, 4.0, 0.0]
    assert result["provenance"]["relative_scale_uncertainty"] == 0
    assert result["provenance"]["calibration_verified"] is False
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("points", [[0, 0, 0], ["3", 4, 0]]),
    ],
)
def test_api_and_saved_workflow_reject_coercion_without_artifact(
    client: TestClient, field: str, value: object
) -> None:
    project_id = str(create_project(client, "Point-cloud numeric integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    invalid = {**PARAMS, field: value}
    response = client.post(f"{base}/spatial/point-cloud-preview", json=invalid)
    assert response.status_code == 422, response.text

    graph = {
        "graph_id": "point-cloud-strict-numbers-v14",
        "name": "Reject coerced calibration or geometry",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": invalid},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "point_cloud_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )
