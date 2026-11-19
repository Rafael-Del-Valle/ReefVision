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
    assert connected["scale_uncertainty_m"] == pytest.approx(0.001)
    assert connected["endpoint_chord_scale_uncertainty_m"] == pytest.approx(0.001)
    assert connected["path_edge_lengths_m"] == pytest.approx([0.01])
    assert connected["path_cumulative_lengths_m"] == pytest.approx([0.0, 0.01])
    assert connected["path_cumulative_length_scale_intervals_m"] == [
        [0.0, 0.0],
        pytest.approx([0.009, 0.011]),
    ]
    assert connected["path_vertices_in_source_frame_m"] == [[0.0, 0.0, 0.0], [0.01, 0.0, 0.0]]
    assert connected["path_edge_length_scale_intervals_m"][0] == pytest.approx([0.009, 0.011])
    for route in expected[1:]:
        assert route["length_scale_interval_m"] is None
        assert route["endpoint_chord_scale_interval_m"] is None
        assert route["path_edge_lengths_m"] is None
        assert route["path_vertices_in_source_frame_m"] is None
        assert route["path_edge_length_scale_intervals_m"] is None
        assert route["path_cumulative_lengths_m"] is None
        assert route["path_cumulative_length_scale_intervals_m"] is None

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
    assert artifact["surface_edge_paths"][0]["path_cumulative_lengths_m"] == pytest.approx(
        [0.0, 0.01]
    )
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
    assert route["path_cumulative_lengths_m"] == pytest.approx([0.0, 0.1, 0.2])
    assert route["path_cumulative_length_scale_intervals_m"] == [
        [0.0, 0.0],
        pytest.approx([0.09, 0.11]),
        pytest.approx([0.18, 0.22]),
    ]
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
    assert route["path_cumulative_lengths_m"][-1] == pytest.approx(route["length_m"])
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [0.0, 1.0])
def test_mesh_route_exact_and_mathematical_zero_bounds_are_distinct(
    uncertainty: float,
) -> None:
    """Exact scale and 100% uncertainty must retain valid route bounds."""
    result = measure_mesh_preview(**PARAMS, relative_scale_uncertainty=uncertainty)
    route = result["surface_edge_paths"][0]
    expected = [0.01 * (1 - uncertainty), 0.01 * (1 + uncertainty)]
    assert route["length_scale_interval_m"] == expected
    assert route["endpoint_chord_scale_interval_m"] == expected
    assert route["scale_uncertainty_m"] == pytest.approx(0.01 * uncertainty)
    assert route["endpoint_chord_scale_uncertainty_m"] == pytest.approx(0.01 * uncertainty)
    assert route["path_edge_length_scale_intervals_m"] == [expected]
    assert route["path_cumulative_length_scale_intervals_m"] == [
        [0.0, 0.0],
        expected,
    ]
    assert "path_scale_interval_below_numeric_resolution" not in route["path_qc_warnings"]


def test_unresolvable_mesh_edge_path_bounds_standalone_and_replayed(
    client: TestClient,
) -> None:
    """Do not serialize an apparently exact measured route with nonzero uncertainty."""
    parameters = {**PARAMS, "relative_scale_uncertainty": 1e-20}
    direct = measure_mesh_preview(**parameters)
    connected = direct["surface_edge_paths"][0]
    assert connected["status"] == "connected"
    assert connected["length_m"] == 0.01
    assert connected["length_scale_interval_m"] is None
    assert connected["endpoint_chord_scale_interval_m"] is None
    assert connected["scale_uncertainty_m"] is None
    assert connected["endpoint_chord_scale_uncertainty_m"] is None
    assert connected["geometric_excess_scale_interval_m"] == [0.0, 0.0]
    assert connected["path_edge_length_scale_intervals_m"] == [None]
    assert connected["path_cumulative_length_scale_intervals_m"] == [
        [0.0, 0.0],
        None,
    ]
    assert "path_scale_interval_below_numeric_resolution" in connected["path_qc_warnings"]
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Unverified sub-resolution mesh route bounds")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["surface_edge_paths"] == direct["surface_edge_paths"]
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["coordinate_registration_verified"] is False
    assert expected["confidence_interval"] is None

    graph = {
        "graph_id": "sub-resolution-route-intervals-v14",
        "name": "Unverified mesh route numeric uncertainty review",
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
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
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


def test_omitted_mesh_route_uncertainty_remains_unknown_in_saved_workflow(
    client: TestClient,
) -> None:
    """No caller uncertainty means no fabricated path bounds or numeric-loss alert."""
    parameters = dict(PARAMS)
    assert "relative_scale_uncertainty" not in parameters
    direct = measure_mesh_preview(**parameters)
    connected = direct["surface_edge_paths"][0]
    assert connected["status"] == "connected"
    assert connected["length_m"] == pytest.approx(0.01)
    assert connected["length_scale_interval_m"] is None
    assert connected["endpoint_chord_scale_interval_m"] is None
    assert connected["geometric_excess_scale_interval_m"] is None
    assert connected["scale_uncertainty_m"] is None
    assert connected["endpoint_chord_scale_uncertainty_m"] is None
    assert connected["path_edge_length_scale_intervals_m"] is None
    assert connected["path_cumulative_length_scale_intervals_m"] is None
    assert "path_scale_interval_below_numeric_resolution" not in connected["path_qc_warnings"]
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Mesh omitted path uncertainty")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["surface_edge_paths"] == direct["surface_edge_paths"]
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["coordinate_registration_verified"] is False
    assert expected["confidence_interval"] is None

    graph = {
        "graph_id": "omitted-route-uncertainty-v14",
        "name": "Unverified mesh route with absent scale uncertainty",
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
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
        assert artifacts[0]["payload_json"] == expected
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
