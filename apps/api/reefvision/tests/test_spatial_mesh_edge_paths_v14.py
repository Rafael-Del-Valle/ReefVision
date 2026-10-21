"""Calibrated provisional mesh-edge routes: standalone and persisted graph parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

PARAMS = {
    "vertices": [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [10, 0, 0],
        [11, 0, 0],
        [10, 1, 0],
        [100, 0, 0],
    ],
    "faces": [[0, 1, 2], [3, 4, 5]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed mesh scale",
    "surface_path_vertex_pairs": [[0, 1], [0, 4], [0, 6]],
}


@pytest.mark.parametrize("uncertainty", [None, 0.1])
def test_mesh_edge_paths_do_not_invent_disconnected_distances(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(
        **PARAMS,
        relative_scale_uncertainty=uncertainty,
    )
    routes = result["surface_edge_paths"]
    assert [route["status"] for route in routes] == [
        "connected",
        "disconnected",
        "unreferenced_endpoint",
    ]
    assert routes[0]["path_vertex_indices"] == [0, 1]
    assert routes[0]["path_qc_warnings"] == ["open_boundary_edge_on_path"]
    assert routes[0]["length_m"] == pytest.approx(0.01)
    assert routes[0]["endpoint_chord_length_m"] == pytest.approx(0.01)
    assert routes[0]["geometric_detour_ratio"] == pytest.approx(1.0)
    assert routes[0]["endpoint_chord_scale_uncertainty_m"] == (
        pytest.approx(0.001) if uncertainty is not None else None
    )
    assert routes[0]["scale_uncertainty_m"] == (
        pytest.approx(0.001) if uncertainty is not None else None
    )
    for route in routes[1:]:
        assert route["length_m"] is None
        assert route["endpoint_chord_length_m"] is None
        assert route["endpoint_chord_scale_uncertainty_m"] is None
        assert route["geometric_detour_ratio"] is None
        assert route["scale_uncertainty_m"] is None
        assert route["path_vertex_indices"] is None
        assert route["path_qc_warnings"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_mesh_edge_paths_flag_nonmanifold_edges_for_review() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]],
        faces=[[0, 1, 2], [1, 0, 3], [0, 1, 4]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Provisional ruler",
        surface_path_vertex_pairs=[[0, 1]],
    )
    route = result["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["length_m"] == pytest.approx(0.1)
    assert route["path_qc_warnings"] == ["nonmanifold_edge_on_path"]
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_mesh_edge_paths_flag_coincident_vertices() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [0, 0, 0], [0, 1, 0]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Provisional ruler",
        surface_path_vertex_pairs=[[0, 1]],
    )
    route = result["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["length_m"] == 0.0
    assert route["endpoint_chord_length_m"] == 0.0
    assert route["geometric_detour_ratio"] is None
    assert route["path_qc_warnings"] == [
        "open_boundary_edge_on_path",
        "zero_length_edge_on_path",
    ]
    assert "degenerate_triangles_present" in result["qc_warnings"]


def test_mesh_edge_path_reports_geometric_detour_not_biological_curvature() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        faces=[[0, 1, 2], [1, 3, 2]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified square mesh scale",
        relative_scale_uncertainty=0.1,
        surface_path_vertex_pairs=[[0, 3]],
    )
    route = result["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["length_m"] == pytest.approx(0.2)
    assert route["endpoint_chord_length_m"] == pytest.approx(2**0.5 * 0.1)
    assert route["endpoint_chord_scale_uncertainty_m"] == pytest.approx(2**0.5 * 0.01)
    assert route["geometric_detour_ratio"] == pytest.approx(2**0.5)
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_mesh_edge_path_rejects_invalid_indices() -> None:
    with pytest.raises(ValueError, match="two distinct existing"):
        measure_mesh_preview(
            **{**PARAMS, "surface_path_vertex_pairs": [[0, 9]]},
        )


def test_saved_mesh_edge_paths_match_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh edge paths")["id"])
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "mesh-edge-paths-v14",
        "name": "Provisional surface paths",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": PARAMS},
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["surface_path_vertex_pairs"]
        == PARAMS["surface_path_vertex_pairs"]
    )
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
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    standalone = client.post(f"{base}/spatial/mesh-preview", json=PARAMS)
    assert standalone.status_code == 200, standalone.text
    assert artifact["surface_edge_paths"] == standalone.json()["surface_edge_paths"]
    assert artifact["surface_edge_paths"][0]["geometric_detour_ratio"] == pytest.approx(1.0)
    assert artifact["surface_edge_paths"][0]["path_qc_warnings"] == ["open_boundary_edge_on_path"]
    assert (
        artifact["provenance"]["geometry_sha256"]
        == (standalone.json()["provenance"]["geometry_sha256"])
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
