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


@pytest.mark.parametrize(
    ("scale", "uncertainty"),
    [
        (0.0, None),
        (-1.0, None),
        (float("nan"), None),
        (float("inf"), None),
        (1.0, -0.1),
        (1.0, 1.0),
        (1.0, float("nan")),
        (1.0, float("inf")),
    ],
)
def test_direct_mesh_path_engine_rejects_invalid_calibration(
    scale: float, uncertainty: float | None
) -> None:
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    with pytest.raises(ValueError, match="Mesh path"):
        mesh_edge_paths(
            points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[[0, 1, 2]],
            pairs=[[0, 1]],
            scale=scale,
            scale_uncertainty=uncertainty,
        )


@pytest.mark.parametrize(
    "faces",
    [
        [[-1, 1, 2]],
        [[0, 1, 3]],
        [[0, 1, 1]],
        [[0, 1]],
        [[0, 1, 2, 2]],
        [[True, 1, 2]],
    ],
)
def test_direct_mesh_path_engine_rejects_invalid_faces(faces: list[list[int]]) -> None:
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    with pytest.raises(ValueError, match="three distinct existing vertex indices"):
        mesh_edge_paths(
            points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=faces,
            pairs=[[0, 1]],
            scale=0.01,
            scale_uncertainty=0.1,
        )


def test_degenerate_triangle_route_is_provisional_and_flagged() -> None:
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    routes = mesh_edge_paths(
        points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        faces=[[0, 1, 2]],
        pairs=[[0, 1]],
        scale=0.01,
        scale_uncertainty=0.1,
    )
    assert routes is not None
    assert routes[0]["status"] == "connected"
    assert routes[0]["length_m"] == pytest.approx(0.01)
    assert routes[0]["path_qc_warnings"] == [
        "degenerate_triangle_on_path",
        "open_boundary_edge_on_path",
    ]


@pytest.mark.parametrize(
    "invalid_point",
    [
        (float("nan"), 0.0, 0.0),
        (float("inf"), 0.0, 0.0),
        (0.0, 0.0),
    ],
)
def test_direct_mesh_path_engine_rejects_invalid_unreferenced_vertices(
    invalid_point: tuple[float, ...],
) -> None:
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    with pytest.raises(ValueError, match="three finite coordinates"):
        mesh_edge_paths(
            points=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                invalid_point,
            ],
            faces=[[0, 1, 2]],
            pairs=[[0, 1]],
            scale=0.01,
            scale_uncertainty=0.1,
        )


def test_mesh_path_uncertainty_overflow_fails_closed() -> None:
    # The nominal edge is finite, but its upper scale bound is not.
    # This direct scientific-engine test does not imply biological validation.
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    with pytest.raises(ValueError, match="uncertainty interval overflowed"):
        mesh_edge_paths(
            points=[(0.0, 0.0, 0.0), (1e308, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[[0, 1, 2]],
            pairs=[[0, 1]],
            scale=1.0,
            scale_uncertainty=0.9,
        )


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
        "degenerate_triangle_on_path",
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
    assert route["geometric_excess_length_m"] == pytest.approx((2 - 2**0.5) * 0.1)
    assert route["geometric_excess_scale_interval_m"] == pytest.approx(
        [(2 - 2**0.5) * 0.09, (2 - 2**0.5) * 0.11]
    )
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
    assert artifact["surface_edge_paths"][0]["geometric_excess_length_m"] == 0.0
    assert artifact["surface_edge_paths"][0]["geometric_excess_scale_interval_m"] is None
    assert artifact["surface_edge_paths"][0]["geometric_detour_ratio"] == pytest.approx(1.0)
    assert artifact["surface_edge_paths"][0]["path_qc_warnings"] == ["open_boundary_edge_on_path"]
    assert (
        artifact["provenance"]["geometry_sha256"]
        == (standalone.json()["provenance"]["geometry_sha256"])
    )
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


def test_overflowing_detour_ratio_is_qc_flagged_and_persists_as_null(
    client: TestClient,
) -> None:
    # The mesh route is finite, but its chord is the smallest subnormal float.
    # Dividing by that chord overflows; Infinity is not valid scientific JSON.
    parameters = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [5e-324, 0, 0]],
        "faces": [[0, 1, 2], [1, 2, 3]],
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified near-coincident endpoints",
        "surface_path_vertex_pairs": [[0, 3]],
    }
    direct = measure_mesh_preview(**parameters)
    route = direct["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["length_m"] == pytest.approx(2.0)
    assert route["endpoint_chord_length_m"] == 5e-324
    assert route["geometric_detour_ratio"] is None
    assert "geometric_detour_ratio_overflow" in route["path_qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"

    project_id = str(create_project(client, "Finite mesh detour ratio")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert response.status_code == 200, response.text
    expected = response.json()["surface_edge_paths"]
    assert expected == direct["surface_edge_paths"]

    graph = {
        "graph_id": "mesh-detour-overflow-v14",
        "name": "Nonfinite detour prevention",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": parameters},
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
    assert artifact["provenance"]["calibration_verified"] is False


def test_calibrated_mesh_edge_underflow_warns_in_standalone_and_saved_graph(
    client: TestClient,
) -> None:
    # Keep the total calibrated surface area representable while a short
    # source-frame edge underflows after calibration. An isolated tiny triangle
    # would now correctly fail the independent zero-area scientific safeguard,
    # so it cannot exercise the route-level QC contract.
    parameters = {
        "vertices": [[0, 0, 0], [1e-170, 0, 0], [0, 1, 0], [-1, 0, 0]],
        "faces": [[0, 1, 2], [0, 2, 3]],
        "meters_per_unit": 1e-160,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified subnormal scale",
        "relative_scale_uncertainty": 0.1,
        "surface_path_vertex_pairs": [[0, 1]],
    }
    direct = measure_mesh_preview(**parameters)
    assert direct["surface_area_m2"] > 0
    assert direct["edge_connected_patch_surface_areas_m2"][0] > 0
    route = direct["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["path_vertex_indices"] == [0, 1]
    assert route["length_m"] == 0
    assert route["endpoint_chord_length_m"] == 0
    assert route["geometric_detour_ratio"] is None
    assert route["path_qc_warnings"] == [
        "calibrated_path_length_underflow",
        "calibrated_endpoint_chord_underflow",
        "open_boundary_edge_on_path",
        "calibrated_path_segment_underflow",
        "calibrated_path_vertex_coordinate_underflow",
    ]
    assert direct["measurement_status"] == "caller_supplied_unverified"

    project_id = str(create_project(client, "Underflow QC mesh edge")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    assert standalone.json()["surface_edge_paths"] == direct["surface_edge_paths"]
    assert standalone.json()["surface_area_m2"] == direct["surface_area_m2"]
    # The direct geometry engine supplies core provenance. Project-scoped API
    # previews enrich it with source and identity QC fields; they are not
    # evidence of verified identity, calibration, or registration.
    api_provenance = standalone.json()["provenance"]
    for key, value in direct["provenance"].items():
        assert api_provenance[key] == value
    assert api_provenance["source_format"] == "indexed_triangles"
    assert api_provenance["source_payload_integrity_checked"] is False
    assert api_provenance["specimen_identity_verified"] is False
    assert api_provenance["observation_metadata_verified"] is False
    assert api_provenance["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "mesh-path-underflow-v14",
        "name": "Calibrated mesh underflow QC",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": parameters},
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
    assert artifact["surface_edge_paths"] == direct["surface_edge_paths"]
    assert artifact["surface_area_m2"] == standalone.json()["surface_area_m2"]
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["provenance"]["calibration_verified"] is False


def test_inconsistent_winding_on_route_persists_in_saved_workflow(
    client: TestClient,
) -> None:
    # Two triangles traverse the same shared edge in the same direction.
    # The shortest path is valid geometry but needs explicit topology review.
    parameters = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0]],
        "faces": [[0, 1, 2], [0, 1, 3]],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified winding test mesh",
        "surface_path_vertex_pairs": [[0, 1]],
    }
    direct = measure_mesh_preview(**parameters)
    route = direct["surface_edge_paths"][0]
    assert route["status"] == "connected"
    assert route["path_vertex_indices"] == [0, 1]
    assert route["length_m"] == pytest.approx(0.1)
    assert route["path_qc_warnings"] == ["inconsistent_winding_edge_on_path"]
    assert "inconsistent_face_winding" in direct["qc_warnings"]
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Winding QC mesh edge")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    assert standalone.json()["surface_edge_paths"] == direct["surface_edge_paths"]

    graph = {
        "graph_id": "mesh-path-winding-v14",
        "name": "Mesh winding route review",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": parameters},
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
    assert artifact["surface_edge_paths"] == direct["surface_edge_paths"]
    assert "inconsistent_face_winding" in artifact["qc_warnings"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


def test_mesh_path_flags_individual_calibrated_segment_underflow() -> None:
    # A tiny edge vanishes under calibration even though the whole route is
    # measurable. The saved route must not silently imply all segments resolved.
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    route = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (1e-170, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 3], [1, 2, 3]],
        pairs=[[0, 2]],
        scale=1e-160,
        scale_uncertainty=0.1,
    )[0]
    assert route["status"] == "connected"
    assert route["length_m"] > 0
    assert route["path_edge_lengths_m"][0] == 0.0
    assert route["path_edge_lengths_m"][1] > 0
    assert "calibrated_path_segment_underflow" in route["path_qc_warnings"]
    assert "calibrated_path_length_underflow" not in route["path_qc_warnings"]


def test_calibrated_segment_underflow_survives_saved_workflow(
    client: TestClient,
) -> None:
    # A positive source edge can underflow in meters. Persist the warning
    # without promoting the result to a verified anatomical measurement.
    parameters = {
        "vertices": [
            [0.0, 0.0, 0.0],
            [1e-170, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        "faces": [[0, 1, 3], [1, 2, 3]],
        "meters_per_unit": 1e-160,
        "calibration_method": "ruler",
        "calibration_evidence": "Provisional synthetic underflow scale",
        "relative_scale_uncertainty": 0.1,
        "surface_path_vertex_pairs": [[0, 2]],
    }
    project_id = str(create_project(client, "Mesh segment underflow parity")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()["surface_edge_paths"][0]
    assert expected["status"] == "connected"
    assert "calibrated_path_segment_underflow" in expected["path_qc_warnings"]

    graph = {
        "graph_id": "mesh-segment-underflow-v14",
        "name": "Provisional segment underflow QC",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": parameters},
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
    assert artifact["surface_edge_paths"][0] == expected
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


def test_disconnected_mesh_paths_preserve_nulls_in_saved_workflow(
    client: TestClient,
) -> None:
    # Disconnected components and unreferenced vertices must never acquire
    # invented physical distances or uncertainty intervals on persistence.
    parameters = {
        **PARAMS,
        "relative_scale_uncertainty": 0.2,
    }
    project_id = str(create_project(client, "Disconnected mesh path parity")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()["surface_edge_paths"]
    assert [route["status"] for route in expected] == [
        "connected",
        "disconnected",
        "unreferenced_endpoint",
    ]
    for route in expected[1:]:
        for field in (
            "length_m",
            "scale_uncertainty_m",
            "endpoint_chord_length_m",
            "endpoint_chord_scale_uncertainty_m",
            "path_vertex_indices",
        ):
            assert route[field] is None

    graph = {
        "graph_id": "disconnected-mesh-paths-v14",
        "name": "No invented disconnected route measurements",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": parameters},
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
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["provenance"]["calibration_verified"] is False


def test_calibrated_mesh_path_vertex_coordinate_underflow_is_flagged() -> None:
    # A finite source coordinate can round to zero in meters. Keep the
    # provisional route but expose the loss of positional precision to review.
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    result = mesh_edge_paths(
        points=[
            (1e-170, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 2]],
        pairs=[[0, 1]],
        scale=1e-160,
        scale_uncertainty=0.1,
    )
    assert result is not None
    route = result[0]
    assert route["status"] == "connected"
    assert route["path_vertices_in_source_frame_m"][0][0] == 0.0
    assert route["length_m"] > 0
    assert "calibrated_path_vertex_coordinate_underflow" in route["path_qc_warnings"]


def test_degenerate_triangle_route_qc_survives_saved_workflow(
    client: TestClient,
) -> None:
    # A collinear triangle is not evidence of a biological centerline.
    # Keep its provisional edge distance and topology warning after persistence.
    parameters = {
        "vertices": [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic collinear triangle, unverified",
        "relative_scale_uncertainty": 0.1,
        "surface_path_vertex_pairs": [[0, 1]],
    }
    project_id = str(create_project(client, "Degenerate mesh route parity")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()["surface_edge_paths"][0]
    assert expected["status"] == "connected"
    assert expected["length_m"] == pytest.approx(0.1)
    assert "degenerate_triangle_on_path" in expected["path_qc_warnings"]
    assert "open_boundary_edge_on_path" in expected["path_qc_warnings"]

    graph = {
        "graph_id": "degenerate-mesh-route-v14",
        "name": "Provisional degenerate mesh route QC",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": parameters},
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
    assert artifact["surface_edge_paths"][0] == expected
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False

    # Re-executing the same persisted graph must not lose scientific QC or
    # silently upgrade provisional calibration to human-verified evidence.
    rerun = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert rerun.status_code == 202, rerun.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(rerun.json()["job_id"])
    )
    rerun_detail = client.get(f"/api/v1/workflow-runs/{rerun.json()['id']}")
    assert rerun_detail.status_code == 200, rerun_detail.text
    assert rerun_detail.json()["run"]["status"] == "succeeded"
    rerun_artifact = next(
        item["payload_json"]
        for item in rerun_detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert rerun_artifact == artifact


def test_degenerate_triangle_off_selected_route_does_not_contaminate_qc() -> None:
    # A defective, disconnected reconstruction patch is not evidence that a
    # separately selected geometric route traverses degenerate triangles.
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    routes = mesh_edge_paths(
        points=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (5.0, 0.0, 0.0),
        ],
        faces=[[0, 1, 2], [3, 4, 5]],
        pairs=[[0, 1], [3, 4]],
        scale=0.1,
        scale_uncertainty=0.1,
    )
    assert routes is not None
    assert routes[0]["status"] == "connected"
    assert routes[0]["length_m"] == pytest.approx(0.1)
    assert "degenerate_triangle_on_path" not in routes[0]["path_qc_warnings"]
    assert routes[1]["status"] == "connected"
    assert "degenerate_triangle_on_path" in routes[1]["path_qc_warnings"]


@pytest.mark.parametrize("duplicate_face", [[0, 1, 2], [2, 1, 0]])
def test_duplicate_triangles_are_route_scoped_and_survive_saved_workflow(
    client: TestClient,
    duplicate_face: list[int],
) -> None:
    # Duplicate faces can corrupt reconstructed topology even when a route
    # remains geometrically measurable. Do not promote it to a centerline.
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    vertices = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [3.0, 0.0, 0.0],
        [4.0, 0.0, 0.0],
        [3.0, 1.0, 0.0],
    ]
    faces = [[0, 1, 2], duplicate_face, [3, 4, 5]]
    routes = mesh_edge_paths(
        points=[tuple(vertex) for vertex in vertices],
        faces=faces,
        pairs=[[0, 1], [3, 4]],
        scale=0.1,
        scale_uncertainty=0.1,
    )
    assert routes is not None
    assert routes[0]["length_m"] == pytest.approx(0.1)
    assert "duplicate_triangle_on_path" in routes[0]["path_qc_warnings"]
    assert "duplicate_triangle_on_path" not in routes[1]["path_qc_warnings"]

    # The low-level route engine reports provisional topology QC, but the
    # project API must reject duplicate faces: they would double-count area.
    parameters = {
        "vertices": vertices,
        "faces": faces,
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic duplicate-face reconstruction; unverified",
        "relative_scale_uncertainty": 0.1,
        "surface_path_vertex_pairs": [[0, 1], [3, 4]],
    }
    project_id = str(create_project(client, "Duplicate mesh face QC parity")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=parameters)
    assert standalone.status_code == 400
    assert standalone.json()["detail"] == "Duplicate triangles would double-count surface area"


def test_mesh_path_rejects_overflowing_triangle_cross_product() -> None:
    # All vertices and individual edge lengths are finite, but the area
    # cross product overflows. Never silently certify the triangle topology.
    from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths

    with pytest.raises(ValueError, match="Mesh triangle cross product overflowed"):
        mesh_edge_paths(
            points=[(0.0, 0.0, 0.0), (1e200, 0.0, 0.0), (0.0, 1e200, 0.0)],
            faces=[[0, 1, 2]],
            pairs=[[0, 1]],
            scale=1e-200,
            scale_uncertainty=0.1,
        )
