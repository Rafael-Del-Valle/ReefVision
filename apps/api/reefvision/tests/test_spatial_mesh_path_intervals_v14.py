"""Scale-only path interval parity across API and persisted Workflow Builder."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_edge_paths_v14 import PARAMS


def test_path_scale_intervals_survive_saved_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh scale intervals")["id"])
    base = f"/api/v1/projects/{project_id}"
    parameters = {**PARAMS, "relative_scale_uncertainty": 0.1}
    response = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert response.status_code == 200, response.text
    expected = response.json()["surface_edge_paths"]
    connected = expected[0]
    assert connected["length_scale_interval_m"] == pytest.approx([0.009, 0.011])
    assert connected["endpoint_chord_scale_interval_m"] == pytest.approx([0.009, 0.011])
    assert connected["path_edge_lengths_m"] == pytest.approx([0.01])
    assert connected["path_vertices_in_source_frame_m"] == [[0.0, 0.0, 0.0], [0.01, 0.0, 0.0]]
    assert connected["path_edge_length_scale_intervals_m"][0] == pytest.approx([0.009, 0.011])
    for route in expected[1:]:
        assert route["length_scale_interval_m"] is None
        assert route["endpoint_chord_scale_interval_m"] is None
        assert route["path_edge_lengths_m"] is None
        assert route["path_vertices_in_source_frame_m"] is None
        assert route["path_edge_length_scale_intervals_m"] is None

    graph = {
        "graph_id": "mesh-path-intervals-v14",
        "name": "Unverified mesh route intervals",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": parameters,
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
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["surface_edge_paths"] == expected
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


def test_two_edge_route_retains_segment_geometry_and_uncertainty() -> None:
    """Report ordered mesh-edge segments without inventing biological branches."""
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        faces=[[0, 1, 2], [1, 3, 2]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
        relative_scale_uncertainty=0.1,
        surface_path_vertex_pairs=[[0, 3]],
    )
    route = result["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["path_vertex_indices"] in ([0, 1, 3], [0, 2, 3])
    assert route["path_edge_lengths_m"] == pytest.approx([0.1, 0.1])
    source_vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]
    expected_vertices = [
        [coordinate * 0.1 for coordinate in source_vertices[index]]
        for index in route["path_vertex_indices"]
    ]
    assert route["path_vertices_in_source_frame_m"] == expected_vertices
    assert len(route["path_vertices_in_source_frame_m"]) == route["edge_count"] + 1
    for interval in route["path_edge_length_scale_intervals_m"]:
        assert interval == pytest.approx([0.09, 0.11])
    assert sum(route["path_edge_lengths_m"]) == pytest.approx(route["length_m"])
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
