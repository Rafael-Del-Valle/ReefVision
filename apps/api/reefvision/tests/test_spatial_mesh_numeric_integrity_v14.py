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
    ("meters_per_unit", 10**1000),
    ("relative_scale_uncertainty", 10**1000),
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
        ("meters_per_unit", 10**1000),
        ("relative_scale_uncertainty", 10**1000),
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
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"]["surface_area_m2"] == standalone["surface_area_m2"]
    assert artifact["payload_json"]["provenance"] == standalone["provenance"]
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert artifact["payload_json"]["provenance"]["calibration_verified"] is False
    assert artifact["payload_json"] == standalone
    assert len(artifact["payload_sha256"]) == 64
    # A single saved measurement node must not silently duplicate scientific outputs.
    assert (
        sum(item["data_type"] == "mesh_measurement_preview" for item in detail.json()["artifacts"])
        == 1
    )


def test_disconnected_patches_preserve_measurements_in_saved_workflow(
    client: TestClient,
) -> None:
    """Independent surface patches are not biological colonies or enclosed volume."""
    project_id = str(create_project(client, "Disconnected mesh patches")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [10, 0, 0],
            [12, 0, 0],
            [10, 2, 0],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
        "meters_per_unit": 1,
        "relative_scale_uncertainty": 0.1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == pytest.approx(2.5)
    assert standalone["edge_connected_patch_count"] == 2
    assert standalone["edge_connected_patch_face_counts"] == [1, 1]
    assert standalone["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.5, 2.0])
    assert standalone["enclosed_volume_m3"] is None
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "disconnected-patches-v14",
        "name": "Disconnected surface patches remain provisional",
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
    artifacts = [
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == standalone
    assert len(artifacts[0]["payload_sha256"]) == 64


@pytest.mark.parametrize("duplicate_vertex_index", [False, True])
def test_vertex_touching_patches_are_not_one_connected_surface(
    client: TestClient,
    duplicate_vertex_index: bool,
) -> None:
    """Shared or coincident vertices do not prove one connected coral surface."""
    project_id = str(create_project(client, "Vertex-touching mesh patches")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [-2, 0, 0],
            [0, -2, 0],
        ],
        "faces": [[0, 1, 2], [5 if duplicate_vertex_index else 0, 3, 4]],
        "meters_per_unit": 1,
    }
    if duplicate_vertex_index:
        # Two vertex IDs at the same XYZ must not imply edge connectivity.
        params["vertices"].append([0, 0, 0])
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == pytest.approx(2.5)
    assert standalone["edge_connected_patch_count"] == 2
    assert standalone["edge_connected_patch_face_counts"] == [1, 1]
    assert standalone["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.5, 2.0])
    assert standalone["enclosed_volume_m3"] is None
    assert standalone["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": "vertex-touching-patches-v14",
        "name": "Do not merge surfaces that touch at only one vertex",
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
    artifacts = [
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == standalone
    assert artifacts[0]["payload_json"]["provenance"]["calibration_verified"] is False
