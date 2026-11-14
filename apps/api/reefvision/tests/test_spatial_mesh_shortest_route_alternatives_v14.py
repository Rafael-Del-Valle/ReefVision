"""Exact-cost mesh route alternatives: provisional QC and saved graph parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths
from reefvision.tests.test_annotations import create_project

GEOMETRY = {
    "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]],
    "faces": [[0, 1, 2], [1, 3, 2]],
    "meters_per_unit": 0.02,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified ruler: route alternatives are mesh geometry only",
    "relative_scale_uncertainty": 0.1,
    "surface_path_vertex_pairs": [[0, 3], [0, 1]],
}


# The additional degenerate triangle has a zero-length edge, but is not
# connected to the calibrated square. It must not hide square route ties.
DISCONNECTED_ZERO_EDGE_GEOMETRY = {
    **GEOMETRY,
    "vertices": [
        *GEOMETRY["vertices"],
        [10.0, 0.0, 0.0],
        [11.0, 0.0, 0.0],
        [11.0, 0.0, 0.0],
    ],
    "faces": [*GEOMETRY["faces"], [4, 5, 6]],
}


def test_tied_mesh_routes_are_not_reported_as_unique_anatomical_paths() -> None:
    paths = mesh_edge_paths(
        points=[tuple(point) for point in GEOMETRY["vertices"]],
        faces=GEOMETRY["faces"],
        pairs=[[0, 3], [0, 1], [3, 0]],
        scale=0.02,
        scale_uncertainty=0.1,
    )
    assert paths is not None
    for tied in (paths[0], paths[2]):
        assert tied["status"] == "connected"
        assert tied["length_m"] == pytest.approx(0.04)
        assert tied["shortest_route_alternatives_status"] == "multiple_exact_equal_cost_routes"
        assert "multiple_equal_cost_mesh_routes" in tied["path_qc_warnings"]
        assert tied["path_turn_angles_deg"] is not None
    assert paths[1]["shortest_route_alternatives_status"] == (
        "no_exact_equal_cost_alternative_detected"
    )
    assert "multiple_equal_cost_mesh_routes" not in paths[1]["path_qc_warnings"]


def test_zero_length_edges_withhold_route_uniqueness_instead_of_guessing() -> None:
    # A zero-weight mesh edge breaks positive-weight shortest-path counting,
    # even when a particular selected route traverses only positive edges.
    paths = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 2], [1, 3, 2], [2, 3, 4]],
        pairs=[[0, 3], [0, 1], [0, 4]],
        scale=0.02,
        scale_uncertainty=None,
    )
    assert paths is not None
    assert all(route["status"] == "connected" for route in paths)
    assert all(
        route["shortest_route_alternatives_status"] == "unassessable_zero_length_edges"
        for route in paths
    )
    assert all(
        "multiple_equal_cost_mesh_routes" not in route["path_qc_warnings"] for route in paths
    )


def test_zero_length_edges_in_other_components_do_not_hide_shortest_route_ties() -> None:
    geometry = DISCONNECTED_ZERO_EDGE_GEOMETRY
    routes = mesh_edge_paths(
        points=[tuple(point) for point in geometry["vertices"]],
        faces=geometry["faces"],
        pairs=[[0, 3], [0, 1], [4, 5]],
        scale=0.02,
        scale_uncertainty=0.1,
    )
    assert routes is not None
    tied, unique, zero_edge_component = routes
    assert tied["shortest_route_alternatives_status"] == "multiple_exact_equal_cost_routes"
    assert "multiple_equal_cost_mesh_routes" in tied["path_qc_warnings"]
    assert unique["shortest_route_alternatives_status"] == (
        "no_exact_equal_cost_alternative_detected"
    )
    assert zero_edge_component["shortest_route_alternatives_status"] == (
        "unassessable_zero_length_edges"
    )


@pytest.mark.parametrize("geometry", (GEOMETRY, DISCONNECTED_ZERO_EDGE_GEOMETRY))
def test_tied_route_qc_roundtrips_standalone_and_persisted_graph(
    client: TestClient, geometry: dict[str, object]
) -> None:
    project_id = str(create_project(client, "Mesh shortest-route tie QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=geometry)
    assert standalone.status_code == 200, standalone.text
    measured = standalone.json()
    tied, unique = measured["surface_edge_paths"]
    assert tied["shortest_route_alternatives_status"] == "multiple_exact_equal_cost_routes"
    assert "multiple_equal_cost_mesh_routes" in tied["path_qc_warnings"]
    assert unique["shortest_route_alternatives_status"] == (
        "no_exact_equal_cost_alternative_detected"
    )
    assert measured["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": "mesh-route-alternatives-v14",
        "name": "Provisional mesh path multiplicity QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": geometry},
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
    assert artifact["provenance"] == measured["provenance"]
    assert artifact["provenance"]["calibration_verified"] is False


# A positive 1e-8 edge cannot be added accurately to a 1e9 accumulated
# route cost in binary64. This is numerical ambiguity, not a biological or
# mathematically exact second shortest route.
ROUNDING_GEOMETRY = {
    "vertices": [[0.0, 0.0, 0.0], [1e9, 0.0, 0.0], [1e9, 1e-8, 0.0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 0.02,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic numerical-resolution reference, unverified",
    "relative_scale_uncertainty": 0.1,
    "surface_path_vertex_pairs": [[0, 2], [0, 1], [2, 0]],
}


def test_positive_edge_cost_roundoff_does_not_claim_exact_route_multiplicity() -> None:
    # 1e9 + 1e-8 == 1e9 in binary64, although the positive edge is real.
    assert 1e9 + 1e-8 == 1e9
    routes = mesh_edge_paths(
        points=[tuple(point) for point in ROUNDING_GEOMETRY["vertices"]],
        faces=ROUNDING_GEOMETRY["faces"],
        pairs=ROUNDING_GEOMETRY["surface_path_vertex_pairs"],
        scale=0.02,
        scale_uncertainty=0.1,
    )
    assert routes is not None
    for route in routes:
        assert route["status"] == "connected"
        assert route["shortest_route_alternatives_status"] == (
            "unassessable_floating_point_cost_resolution"
        )
        assert "positive_mesh_edge_cost_rounded_away" in route["path_qc_warnings"]
        assert "multiple_equal_cost_mesh_routes" not in route["path_qc_warnings"]
        assert route["length_m"] == pytest.approx(2e7)


def test_subresolution_prefix_is_not_mistaken_for_an_exact_route_tie() -> None:
    # The shortest candidate 2 -> 1 -> 0 adds a huge edge *after*
    # a tiny positive prefix. The prefix vanishes in the rounded total,
    # even though no positive edge was rounded away at the moment it was
    # added. The direct route is shorter in exact stored-edge arithmetic.
    paths = mesh_edge_paths(
        points=[tuple(point) for point in ROUNDING_GEOMETRY["vertices"]],
        faces=ROUNDING_GEOMETRY["faces"],
        pairs=[[2, 0]],
        scale=0.02,
        scale_uncertainty=0.1,
    )
    assert paths is not None
    assert paths[0]["shortest_route_alternatives_status"] == (
        "unassessable_floating_point_cost_resolution"
    )
    assert "positive_mesh_edge_cost_rounded_away" in paths[0]["path_qc_warnings"]
    assert "multiple_equal_cost_mesh_routes" not in paths[0]["path_qc_warnings"]


def test_route_roundoff_qc_roundtrips_standalone_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Mesh path floating precision QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=ROUNDING_GEOMETRY)
    assert standalone.status_code == 200, standalone.text
    measured = standalone.json()
    assert all(
        route["shortest_route_alternatives_status"] == "unassessable_floating_point_cost_resolution"
        for route in measured["surface_edge_paths"]
    )
    assert measured["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": "mesh-route-roundoff-v14",
        "name": "Floating precision path multiplicity QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": ROUNDING_GEOMETRY,
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
    assert artifact["provenance"] == measured["provenance"]
    assert artifact["provenance"]["calibration_verified"] is False
