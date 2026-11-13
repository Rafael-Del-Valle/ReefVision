"""Provisional route turning angles: numeric references and saved-workflow parity."""

from __future__ import annotations

from math import atan, degrees, hypot
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

GEOMETRY = {
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
    "faces": [[0, 1, 2], [1, 3, 2]],
    "meters_per_unit": 0.02,
    "calibration_method": "ruler",
    "calibration_evidence": "Caller-supplied, not independently verified",
    "relative_scale_uncertainty": 0.1,
    "surface_path_vertex_pairs": [[0, 3], [0, 1]],
}


def test_route_turns_are_geometric_and_scale_invariant() -> None:
    for scale in (0.02, 2.0):
        measurement = measure_mesh_preview(**{**GEOMETRY, "meters_per_unit": scale})
        corner, single_edge = measurement["surface_edge_paths"]
        assert corner["status"] == "connected"
        assert corner["path_turn_angles_deg"] == [None, pytest.approx(90.0), None]
        assert corner["maximum_turn_angle_deg"] == pytest.approx(90.0)
        assert corner["total_absolute_geometric_turn_deg"] == pytest.approx(90.0)
        assert corner["length_m"] == pytest.approx(2 * scale)
        assert single_edge["path_turn_angles_deg"] == [None, None]
        assert single_edge["maximum_turn_angle_deg"] is None
        # A single valid edge has no interior bends; this is zero, not missing.
        assert single_edge["total_absolute_geometric_turn_deg"] == 0.0
        assert measurement["measurement_status"] == "caller_supplied_unverified"


def test_straight_route_turn_is_zero_not_missing() -> None:
    paths = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 3], [1, 2, 3]],
        pairs=[[0, 2]],
        scale=1.0,
        scale_uncertainty=None,
    )
    assert paths is not None
    assert paths[0]["path_vertex_indices"] == [0, 1, 2]
    assert paths[0]["path_turn_angles_deg"] == [None, pytest.approx(0.0), None]
    assert paths[0]["maximum_turn_angle_deg"] == pytest.approx(0.0)
    assert paths[0]["total_absolute_geometric_turn_deg"] == pytest.approx(0.0)


def test_total_turn_reports_multiple_bends_not_just_largest_bend() -> None:
    # Three triangles touch at successive vertices, forcing a route with
    # distinct 90-degree bends while keeping each triangle nondegenerate.
    paths = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (1.0, 0.0, 1.0),
            (1.0, 1.0, 0.0),
            (1.0, 1.0, 1.0),
            (2.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 2], [2, 3, 4], [4, 5, 6]],
        pairs=[[0, 6]],
        scale=0.02,
        scale_uncertainty=0.1,
    )
    assert paths is not None
    route = paths[0]
    assert route["path_vertex_indices"] == [0, 2, 4, 6]
    assert route["path_turn_angles_deg"] == [
        None,
        pytest.approx(90.0),
        pytest.approx(90.0),
        None,
    ]
    assert route["maximum_turn_angle_deg"] == pytest.approx(90.0)
    assert route["total_absolute_geometric_turn_deg"] == pytest.approx(180.0)
    assert route["length_m"] == pytest.approx(0.06)


@pytest.mark.parametrize(
    ("lateral", "vertical"),
    [(1e-9, 0.0), (-1e-9, 0.0), (0.0, 1e-9)],
)
def test_tiny_genuine_bends_do_not_round_to_zero(lateral: float, vertical: float) -> None:
    # acos(dot) rounded the cosine of these valid tiny turns to exactly 1,
    # producing a false zero despite a nonzero 3D change of direction.
    paths = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, lateral, vertical),
            (1.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 3], [1, 2, 3]],
        pairs=[[0, 2]],
        scale=0.02,
        scale_uncertainty=0.1,
    )
    assert paths is not None
    route = paths[0]
    assert route["path_vertex_indices"] == [0, 1, 2]
    assert route["path_turn_angles_deg"][0] is None
    assert route["path_turn_angles_deg"][2] is None
    expected = degrees(atan(hypot(lateral, vertical)))
    assert route["path_turn_angles_deg"][1] == pytest.approx(expected, rel=1e-6)
    assert route["path_turn_angles_deg"][1] > 0
    assert route["maximum_turn_angle_deg"] == pytest.approx(expected, rel=1e-6)
    assert route["total_absolute_geometric_turn_deg"] == pytest.approx(expected, rel=1e-6)


def test_zero_length_incident_edge_keeps_undefined_turn_unknown() -> None:
    paths = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 2], [1, 3, 4]],
        pairs=[[0, 3], [0, 4]],
        scale=1.0,
        scale_uncertainty=0.1,
    )
    assert paths is not None
    assert paths[0]["path_vertex_indices"] == [0, 1, 3]
    assert paths[0]["path_turn_angles_deg"] == [None, None, None]
    assert paths[0]["maximum_turn_angle_deg"] is None
    # Undefined interior bend cannot be mistaken for a perfectly straight route.
    assert paths[0]["total_absolute_geometric_turn_deg"] is None
    assert "zero_length_edge_on_path" in paths[0]["path_qc_warnings"]


def test_route_turns_roundtrip_in_typed_persisted_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Unverified route turns")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=GEOMETRY)
    assert standalone.status_code == 200, standalone.text
    measured = standalone.json()
    route = measured["surface_edge_paths"][0]
    assert route["path_turn_angles_deg"] == [None, pytest.approx(90.0), None]
    assert route["maximum_turn_angle_deg"] == pytest.approx(90.0)
    assert route["total_absolute_geometric_turn_deg"] == pytest.approx(90.0)

    graph = {
        "graph_id": "mesh-turn-angles-v14",
        "name": "Provisional geometric route bends",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": GEOMETRY,
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
    assert artifact["surface_edge_paths"] == measured["surface_edge_paths"]
    assert artifact["surface_edge_paths"][0]["total_absolute_geometric_turn_deg"] == pytest.approx(
        90.0
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"] == measured["provenance"]
    assert artifact["provenance"]["calibration_verified"] is False
