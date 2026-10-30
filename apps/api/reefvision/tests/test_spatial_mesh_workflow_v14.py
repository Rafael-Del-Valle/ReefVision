"""Saved workflow and standalone API regression for ReefVision 1.4 mesh previews."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project

MESH = {
    "obj_text": "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n",
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Known scale bar, unreviewed",
    "relative_scale_uncertainty": 0.05,
}


def test_mesh_preview_api_is_unverified(client: TestClient) -> None:
    project = create_project(client, "Mesh preview API")
    response = client.post(f"/api/v1/projects/{project['id']}/spatial/mesh-preview", json=MESH)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(3 / 13)
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
    homogeneous = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={
            **MESH,
            "obj_text": "v 0 0 0 2\nv 4 0 0 2\nv 0 6 0 2\nf 1 2 3\n",
        },
    )
    assert homogeneous.status_code == 200, homogeneous.text
    assert (
        homogeneous.json()["provenance"]["geometry_sha256"]
        == (result["provenance"]["geometry_sha256"])
    )
    assert homogeneous.json()["area_scale_uncertainty_m2"] == pytest.approx(
        result["area_scale_uncertainty_m2"]
    )
    invalid = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={**MESH, "obj_text": "v 0 0 0\nf 1 2 3"},
    )
    assert invalid.status_code == 400


@pytest.mark.parametrize("scale", [0.001, 0.01, 10.0])
@pytest.mark.parametrize("uncertainty", [None, 0.0, 0.5])
def test_mesh_shape_ratio_cancels_common_scale_only(
    client: TestClient, scale: float, uncertainty: float | None
) -> None:
    project = create_project(client, "Mesh shape ratio")
    response = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={**MESH, "meters_per_unit": scale, "relative_scale_uncertainty": uncertainty},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_to_bounding_diagonal_squared_ratio"] == pytest.approx(
        3 / 13
    )
    assert result["provenance"]["calibration_verified"] is False


def test_mesh_shape_ratio_withholds_zero_diagonal(client: TestClient) -> None:
    project = create_project(client, "Degenerate mesh shape ratio")
    response = client.post(
        f"/api/v1/projects/{project['id']}/spatial/mesh-preview",
        json={
            **MESH,
            "obj_text": "v 0 0 0\nv 0 0 0\nv 0 0 0\nf 1 2 3\n",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["surface_area_to_bounding_diagonal_squared_ratio"] is None


@pytest.mark.parametrize(
    "obj_text",
    [
        pytest.param(MESH["obj_text"], id="cartesian"),
        pytest.param("v 0 0 0 2\nv 4 0 0 2\nv 0 6 0 2\nf 1 2 3\n", id="homogeneous"),
    ],
)
def test_saved_mesh_workflow_roundtrip(client: TestClient, obj_text: str) -> None:
    project = create_project(client, "Mesh workflow")
    project_id = str(project["id"])
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(item for item in registry.json() if item["node_type"] == "mesh_surface_preview")
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["mesh_measurement_preview"]
    graph = {
        "graph_id": "mesh-preview-v14",
        "name": "Calibrated triangle preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": {**MESH, "obj_text": obj_text},
            },
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
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["graph_json"]["nodes"][1]["parameters"]["obj_text"] == obj_text
    run = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": record["id"]},
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(0.0003)
    shape_ratio = artifact["payload_json"]["surface_area_to_bounding_diagonal_squared_ratio"]
    assert shape_ratio == pytest.approx(3 / 13)
    assert artifact["payload_json"]["project_id"] == project_id
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert len(artifact["payload_sha256"]) == 64
    assert artifact["payload_json"]["area_scale_uncertainty_m2"] == pytest.approx(0.00003)
    assert artifact["payload_json"]["axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        0.01 * 13**0.5
    )
    measured = artifact["payload_json"]
    assert measured["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [0.001, 0.0015, 0.0]
    )
    assert artifact["payload_json"]["provenance"]["source_format"] == "obj"
    assert artifact["payload_json"]["provenance"]["calibration_verified"] is False
    standalone = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-preview",
        json={**MESH, "obj_text": obj_text},
    )
    assert standalone.status_code == 200, standalone.text
    assert artifact["payload_json"]["surface_area_m2"] == pytest.approx(
        standalone.json()["surface_area_m2"]
    )
    assert artifact["payload_json"]["surface_area_to_bounding_diagonal_squared_ratio"] == (
        standalone.json()["surface_area_to_bounding_diagonal_squared_ratio"]
    )
    assert (
        artifact["payload_json"]["provenance"]["geometry_sha256"]
        == standalone.json()["provenance"]["geometry_sha256"]
    )


def test_unverified_mesh_artifact_cannot_feed_project_input(client: TestClient) -> None:
    project = create_project(client, "Mesh typing")
    graph = {
        "graph_id": "mesh-bad-edge",
        "name": "Prevent mesh preview as project",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": MESH},
            {"node_id": "images", "node_type": "project_images"},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            },
            {
                "edge_id": "bad",
                "source_node_id": "mesh",
                "source_port_id": "measurement",
                "target_node_id": "images",
                "target_port_id": "project",
            },
        ],
    }
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200
    assert any(issue["code"] == "incompatible_port_types" for issue in response.json()["issues"])


def test_saved_mesh_workflow_preserves_topology_qc(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh topology workflow")["id"])
    params = {
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [10, 0, 0],
            [11, 0, 0],
            [10, 1, 0],
            [1000, 1000, 1000],
        ],
        "faces": [[0, 1, 2], [0, 3, 2], [4, 5, 6]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed control target",
        "relative_scale_uncertainty": 0.05,
    }
    graph = {
        "graph_id": "mesh-topology-qc-v14",
        "name": "Topology QC",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }
    base = f"/api/v1/projects/{project_id}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    assert artifact["edge_connected_patch_count"] == 2
    assert artifact["inconsistent_winding_edge_count"] == 1
    assert artifact["unreferenced_vertex_count"] == 1
    assert artifact["axis_aligned_dimensions_m"] == pytest.approx([0.11, 0.01, 0.0])
    assert artifact["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx(
        [0.0055, 0.0005, 0.0]
    )
    assert "unreferenced_mesh_vertices" in artifact["qc_warnings"]
    assert "disconnected_mesh_patches" in artifact["qc_warnings"]
    assert "inconsistent_face_winding" in artifact["qc_warnings"]
    for field in (
        "edge_connected_patch_count",
        "inconsistent_winding_edge_count",
        "unreferenced_vertex_count",
        "axis_aligned_dimensions_m",
        "axis_aligned_dimension_scale_uncertainty_m",
        "axis_aligned_bounding_box_diagonal_m",
        "axis_aligned_bounding_box_diagonal_scale_uncertainty_m",
        "edge_connected_patch_bounding_box_diagonals_m",
        "edge_connected_patch_bounding_box_diagonal_scale_uncertainties_m",
    ):
        assert artifact[field] == standalone.json()[field]
    assert (
        artifact["provenance"]["geometry_sha256"]
        == (standalone.json()["provenance"]["geometry_sha256"])
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
