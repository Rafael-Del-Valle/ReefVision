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


def test_shared_edge_surface_is_one_patch_in_saved_workflow(client: TestClient) -> None:
    """Edge adjacency joins triangles, without implying closed biological volume."""
    project_id = str(create_project(client, "Shared-edge mesh surface")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        "faces": [[0, 1, 2], [0, 2, 3]],
        "meters_per_unit": 1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == pytest.approx(1.0)
    assert standalone["edge_connected_patch_count"] == 1
    assert standalone["edge_connected_patch_face_counts"] == [2]
    assert standalone["edge_connected_patch_surface_areas_m2"] == pytest.approx([1.0])
    assert standalone["boundary_edge_count"] == 4
    assert standalone["enclosed_volume_m3"] is None
    assert standalone["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": "shared-edge-surface-v14",
        "name": "Shared-edge open surface geometry",
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


def test_closed_tetrahedron_volume_is_provisional_and_workflow_reproducible(
    client: TestClient,
) -> None:
    """A closed oriented reference tetrahedron has known geometric, not biological, volume."""
    project_id = str(create_project(client, "Closed tetrahedron reference")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "faces": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        "meters_per_unit": 1,
        "relative_scale_uncertainty": 0.1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == pytest.approx(1.5 + 3**0.5 / 2)
    assert standalone["enclosed_volume_m3"] == pytest.approx(1 / 6)
    # Scale uncertainty compounds quadratically for area and cubically for volume.
    # These are scale-only bounds, not biological confidence intervals.
    expected_area = 1.5 + 3**0.5 / 2
    assert standalone["surface_area_scale_interval_m2"] == pytest.approx(
        [expected_area * 0.9**2, expected_area * 1.1**2]
    )
    assert standalone["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [(1 / 6) * 0.9**3, (1 / 6) * 1.1**3]
    )
    # Linear dimensions and inverse-length A/V must use different scale exponents.
    # These are source-frame geometry diagnostics, never anatomical branch lengths.
    assert standalone["axis_aligned_dimensions_m"] == pytest.approx([1, 1, 1])
    for interval in standalone["axis_aligned_dimension_scale_intervals_m"]:
        assert interval == pytest.approx([0.9, 1.1])
    assert standalone["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(3**0.5)
    assert standalone["axis_aligned_bounding_box_diagonal_scale_interval_m"] == pytest.approx(
        [3**0.5 * 0.9, 3**0.5 * 1.1]
    )
    expected_ratio = expected_area / (1 / 6)
    assert standalone["surface_to_enclosed_volume_ratio_per_m"] == pytest.approx(expected_ratio)
    assert standalone["surface_to_enclosed_volume_ratio_scale_interval_per_m"] == pytest.approx(
        [expected_ratio / 1.1, expected_ratio / 0.9]
    )
    assert standalone["confidence_interval"] is None
    assert standalone["boundary_edge_count"] == 0
    assert standalone["edge_connected_patch_count"] == 1
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "closed-tetrahedron-reference-v14",
        "name": "Closed reference geometry with provisional volume",
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


def test_full_scale_uncertainty_withholds_unbounded_inverse_scale_interval_in_workflow(
    client: TestClient,
) -> None:
    """At 100% scale uncertainty, A/V has no finite upper scale-only bound."""
    project_id = str(create_project(client, "Unbounded inverse-scale reference")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "faces": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
        "meters_per_unit": 1,
        "relative_scale_uncertainty": 1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["enclosed_volume_m3"] == pytest.approx(1 / 6)
    assert standalone["surface_to_enclosed_volume_ratio_per_m"] is not None
    assert standalone["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
    assert standalone["confidence_interval"] is None
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "unbounded-inverse-scale-v14",
        "name": "Do not invent a finite inverse-scale upper bound",
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


def test_disconnected_surface_paths_withhold_length_in_saved_workflow(
    client: TestClient,
) -> None:
    """Only connected mesh-edge routes yield geometric distances, never branch lengths."""
    project_id = str(create_project(client, "Disconnected surface path QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [10, 0, 0],
            [11, 0, 0],
            [10, 1, 0],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
        "surface_path_vertex_pairs": [[1, 2], [0, 4]],
        "meters_per_unit": 1,
        "relative_scale_uncertainty": 0.1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    paths = standalone["surface_edge_paths"]
    assert len(paths) == 2
    connected, disconnected = paths
    assert connected["status"] == "connected"
    assert connected["path_vertex_indices"] == [1, 2]
    assert connected["length_m"] == pytest.approx(2**0.5)
    assert connected["length_scale_interval_m"] == pytest.approx([2**0.5 * 0.9, 2**0.5 * 1.1])
    assert connected["path_cumulative_lengths_m"] == pytest.approx([0, 2**0.5])
    assert "open_boundary_edge_on_path" in connected["path_qc_warnings"]
    assert disconnected["status"] == "disconnected"
    assert disconnected["path_vertex_indices"] is None
    assert disconnected["length_m"] is None
    assert disconnected["length_scale_interval_m"] is None
    assert disconnected["path_cumulative_lengths_m"] is None
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "disconnected-surface-path-qc-v14",
        "name": "Withhold disconnected geometric path measurements",
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


def test_multihop_surface_route_uses_mesh_edges_in_saved_workflow(
    client: TestClient,
) -> None:
    """A surface path follows connected mesh edges, not the straight-line chord."""
    project_id = str(create_project(client, "Multi-hop surface path reference")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 2, 0], [2, 0, 0]],
        "faces": [[0, 1, 2], [1, 3, 2]],
        "surface_path_vertex_pairs": [[0, 3]],
        "meters_per_unit": 1,
        "relative_scale_uncertainty": 0.1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    paths = standalone["surface_edge_paths"]
    assert len(paths) == 1
    route = paths[0]
    assert route["status"] == "connected"
    assert route["path_vertex_indices"] == [0, 1, 3]
    assert route["length_m"] == pytest.approx(2)
    assert route["path_cumulative_lengths_m"] == pytest.approx([0, 1, 2])
    assert route["path_edge_lengths_m"] == pytest.approx([1, 1])
    assert route["path_vertices_in_source_frame_m"] == [
        [0, 0, 0],
        [1, 0, 0],
        [2, 0, 0],
    ]
    for interval in route["path_edge_length_scale_intervals_m"]:
        assert interval == pytest.approx([0.9, 1.1])
    for interval, expected in zip(
        route["path_cumulative_length_scale_intervals_m"],
        ([0, 0], [0.9, 1.1], [1.8, 2.2]),
        strict=True,
    ):
        assert interval == pytest.approx(expected)
    assert route["endpoint_chord_length_m"] == pytest.approx(2)
    assert route["geometric_detour_ratio"] == pytest.approx(1)
    assert route["length_scale_interval_m"] == pytest.approx([1.8, 2.2])
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "multihop-mesh-route-v14",
        "name": "Multi-hop provisional surface path reference",
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


def test_noncollinear_mesh_route_detour_is_preserved_in_saved_workflow(
    client: TestClient,
) -> None:
    """A bent surface route must exceed its straight-line chord without claiming anatomy."""
    project_id = str(create_project(client, "Bent surface path reference")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 1, 0], [0, 3, 0], [2, 0, 0]],
        "faces": [[0, 1, 2], [1, 3, 2]],
        "surface_path_vertex_pairs": [[0, 3]],
        "meters_per_unit": 1,
        "relative_scale_uncertainty": 0.1,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    paths = standalone["surface_edge_paths"]
    assert len(paths) == 1
    route = paths[0]
    assert route["status"] == "connected"
    assert route["path_vertex_indices"] == [0, 1, 3]
    assert route["length_m"] == pytest.approx(2 * 2**0.5)
    assert route["path_cumulative_lengths_m"] == pytest.approx([0, 2**0.5, 2 * 2**0.5])
    assert route["path_edge_lengths_m"] == pytest.approx([2**0.5, 2**0.5])
    assert route["path_vertices_in_source_frame_m"] == [
        [0, 0, 0],
        [1, 1, 0],
        [2, 0, 0],
    ]
    for interval in route["path_edge_length_scale_intervals_m"]:
        assert interval == pytest.approx([2**0.5 * 0.9, 2**0.5 * 1.1])
    for interval, expected in zip(
        route["path_cumulative_length_scale_intervals_m"],
        (
            [0, 0],
            [2**0.5 * 0.9, 2**0.5 * 1.1],
            [2 * 2**0.5 * 0.9, 2 * 2**0.5 * 1.1],
        ),
        strict=True,
    ):
        assert interval == pytest.approx(expected)
    assert route["endpoint_chord_length_m"] == pytest.approx(2)
    assert route["geometric_detour_ratio"] == pytest.approx(2**0.5)
    assert route["length_scale_interval_m"] == pytest.approx([2 * 2**0.5 * 0.9, 2 * 2**0.5 * 1.1])
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "bent-mesh-route-v14",
        "name": "Bent provisional surface path reference",
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


def test_mesh_route_calibration_rescales_lengths_not_detour_in_saved_workflow(
    client: TestClient,
) -> None:
    """Physical lengths change with calibration; the geometric detour ratio does not."""
    project_id = str(create_project(client, "Calibrated bent mesh route")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 1, 0], [0, 3, 0], [2, 0, 0]],
        "faces": [[0, 1, 2], [1, 3, 2]],
        "surface_path_vertex_pairs": [[0, 3]],
        "meters_per_unit": 0.5,
        "relative_scale_uncertainty": 0.2,
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    route = standalone["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["path_vertex_indices"] == [0, 1, 3]
    assert route["length_m"] == pytest.approx(2**0.5)
    assert route["endpoint_chord_length_m"] == pytest.approx(1)
    assert route["geometric_detour_ratio"] == pytest.approx(2**0.5)
    assert route["path_edge_lengths_m"] == pytest.approx([2**0.5 / 2] * 2)
    assert route["length_scale_interval_m"] == pytest.approx(
        [2**0.5 * 0.8, 2**0.5 * 1.2]
    )
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "calibrated-bent-mesh-route-v14",
        "name": "Calibrated provisional geometric route",
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
