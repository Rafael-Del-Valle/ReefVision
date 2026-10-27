"""Reject implicit numeric coercion in calibrated mesh geometry and saved workflows."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

PARAMS: dict[str, Any] = {
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed field ruler",
    "relative_scale_uncertainty": 0.1,
}

INVALID_NUMBERS = [
    ("meters_per_unit", True),
    ("meters_per_unit", "0.01"),
    ("relative_scale_uncertainty", False),
    ("relative_scale_uncertainty", "0.1"),
    ("vertices", [[True, 0, 0], [1, 0, 0], [0, 1, 0]]),
    ("vertices", [["0", 0, 0], [1, 0, 0], [0, 1, 0]]),
]


@pytest.mark.parametrize(("field", "value"), INVALID_NUMBERS)
def test_mesh_schema_rejects_coerced_numbers(field: str, value: object) -> None:
    with pytest.raises(PydanticValidationError):
        MeshPreviewRequest.model_validate({**PARAMS, field: value})


@pytest.mark.parametrize(("field", "value"), INVALID_NUMBERS)
def test_mesh_service_rejects_coerced_numbers(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        measure_mesh_preview(**{**PARAMS, field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("meters_per_unit", True),
        ("relative_scale_uncertainty", "0.1"),
        ("vertices", [[0, 0, 0], ["1", 0, 0], [0, 1, 0]]),
    ],
)
def test_invalid_mesh_numbers_fail_api_and_persisted_workflow_without_artifact(
    client: TestClient, field: str, value: object
) -> None:
    project_id = str(create_project(client, "Strict mesh scientific numbers")["id"])
    base = f"/api/v1/projects/{project_id}"
    invalid = {**PARAMS, field: value}
    response = client.post(f"{base}/spatial/mesh-preview", json=invalid)
    assert response.status_code == 422, response.text

    graph = {
        "graph_id": "strict-mesh-scientific-numbers-v14",
        "name": "Reject coerced mesh geometry and calibration",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": invalid},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
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
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_valid_integer_mesh_geometry_retains_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "Integer mesh scientific inputs")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {**PARAMS, "meters_per_unit": 1, "relative_scale_uncertainty": 0}
    request = MeshPreviewRequest.model_validate(params)
    expected = measure_mesh_preview(
        vertices=request.vertices,
        faces=request.faces,
        meters_per_unit=request.meters_per_unit,
        calibration_method=request.calibration_method,
        calibration_evidence=request.calibration_evidence,
        relative_scale_uncertainty=request.relative_scale_uncertainty,
    )
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == pytest.approx(0.5)
    assert standalone["surface_area_m2"] == expected["surface_area_m2"]
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "valid-integer-mesh-numbers-v14",
        "name": "Preserve exact integer mesh scientific inputs",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail.json()["artifacts"] if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"]["surface_area_m2"] == standalone["surface_area_m2"]
    assert artifact["payload_json"]["provenance"] == standalone["provenance"]
    assert len(artifact["payload_sha256"]) == 64
