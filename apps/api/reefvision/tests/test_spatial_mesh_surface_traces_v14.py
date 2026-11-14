"""Caller-selected triangle-edge traces: provisional geometry and saved-workflow parity."""

from __future__ import annotations

from math import sqrt
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_paths_v14 import mesh_surface_edge_traces
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

PARAMS = {
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Provisional ruler observation, not an anatomical centerline",
    "relative_scale_uncertainty": 0.1,
    "surface_path_vertex_pairs": [[0, 1]],
    "surface_trace_vertex_paths": [[0, 2, 1]],
}

# The second calibrated segment is real, but adding it to the first is
# beyond float precision. The standalone API and saved workflow must retain
# the individual edge length and report the unresolved cumulative waypoint.
RESOLUTION_LIMITED_PARAMS = {
    **PARAMS,
    "vertices": [[0, 0, 0], [1, 0, 0], [1, 1e-17, 0]],
    "surface_trace_vertex_paths": [[0, 1, 2]],
}

# Repeated triangles with reversed winding and two distinct faces whose shared
# edge is traversed in the same direction have different scientific defects.
# Neither defect implies that a selected trace is a biological centerline.
DUPLICATE_FACE_PARAMS = {
    **PARAMS,
    "faces": [[0, 1, 2], [2, 1, 0]],
    "surface_trace_vertex_paths": [[0, 1]],
}
INCONSISTENT_WINDING_PARAMS = {
    **PARAMS,
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "faces": [[0, 1, 2], [0, 1, 3]],
    "surface_trace_vertex_paths": [[0, 1]],
}
# Each indexed edge has a positive length and no vertex ID repeats, yet
# waypoints 0 and 2 coincide spatially across distinct indexed faces.
COINCIDENT_NONADJACENT_PARAMS = {
    **PARAMS,
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 1, 0], [1, -1, 0]],
    "faces": [[0, 1, 3], [1, 2, 4]],
    "surface_trace_vertex_paths": [[0, 1, 2]],
}
# A 180-degree turn retraces part of an edge without reusing indices,
# coincident vertices, or a zero-length segment. The triangles are
# nondegenerate and indexed differently; this is provisional mesh QC.
REVERSE_TURN_PARAMS = {
    **PARAMS,
    "vertices": [[0, 0, 0], [2, 0, 0], [1, 0, 0], [0, 1, 0], [2, 1, 0]],
    "faces": [[0, 1, 3], [1, 2, 4]],
    "surface_trace_vertex_paths": [[0, 1, 2]],
}


def test_trace_follows_selected_edges_not_the_shortest_route() -> None:
    result = measure_mesh_preview(**PARAMS)
    trace = result["surface_edge_traces"][0]
    assert trace["trace_type"] == "caller_selected_mesh_surface_edges"
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"
    assert trace["human_review_verified"] is False
    assert trace["vertex_indices"] == [0, 2, 1]
    assert trace["vertices_in_source_frame_m"] == [
        [0.0, 0.0, 0.0],
        [0.0, 0.01, 0.0],
        [0.01, 0.0, 0.0],
    ]
    assert trace["segment_lengths_m"] == pytest.approx([0.01, sqrt(2) * 0.01])
    expected = (1 + sqrt(2)) * 0.01
    assert trace["length_m"] == pytest.approx(expected)
    assert trace["cumulative_lengths_m"] == pytest.approx([0.0, 0.01, expected])
    segment_bounds = trace["segment_length_scale_only_intervals_m"]
    assert segment_bounds[0] == pytest.approx([0.009, 0.011])
    assert segment_bounds[1] == pytest.approx([sqrt(2) * 0.009, sqrt(2) * 0.011])
    cumulative_bounds = trace["cumulative_length_scale_only_intervals_m"]
    assert cumulative_bounds[0] == [0.0, 0.0]
    assert cumulative_bounds[1] == pytest.approx([0.009, 0.011])
    assert cumulative_bounds[2] == pytest.approx([expected * 0.9, expected * 1.1])
    assert trace["length_scale_only_interval_m"] == pytest.approx([expected * 0.9, expected * 1.1])
    assert trace["length_m"] > result["surface_edge_paths"][0]["length_m"]
    assert trace["qc_warnings"] == [
        "caller_selected_surface_trace_not_anatomical_centerline",
        "open_boundary_edge_on_surface_trace",
    ]
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_selected_trace_turn_angles_are_scale_invariant_and_provisional() -> None:
    first = measure_mesh_preview(**PARAMS)["surface_edge_traces"][0]
    rescaled_params = {**PARAMS, "meters_per_unit": 0.02}
    rescaled = measure_mesh_preview(**rescaled_params)["surface_edge_traces"][0]
    for trace in (first, rescaled):
        assert trace["turn_angles_deg"][0] is None
        assert trace["turn_angles_deg"][1] == pytest.approx(135.0)
        assert trace["turn_angles_deg"][2] is None
        assert trace["maximum_turn_angle_deg"] == pytest.approx(135.0)
        assert trace["total_absolute_geometric_turn_deg"] == pytest.approx(135.0)
        assert trace["human_review_verified"] is False
        assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"
    assert first["turn_angles_deg"] == rescaled["turn_angles_deg"]


@pytest.mark.parametrize("scale", [0.01, 0.02])
def test_selected_trace_endpoint_chord_and_detour_are_scale_invariant(scale: float) -> None:
    result = measure_mesh_preview(**{**PARAMS, "meters_per_unit": scale})
    trace = result["surface_edge_traces"][0]
    assert trace["endpoint_chord_length_m"] == pytest.approx(scale)
    assert trace["endpoint_chord_scale_only_interval_m"] == pytest.approx(
        [0.9 * scale, 1.1 * scale]
    )
    assert trace["geometric_detour_ratio"] == pytest.approx(1 + sqrt(2))
    assert trace["human_review_verified"] is False


def test_coincident_trace_endpoints_have_unknown_detour_not_infinity() -> None:
    trace = measure_mesh_preview(**COINCIDENT_NONADJACENT_PARAMS)["surface_edge_traces"][0]
    assert trace["length_m"] > 0
    assert trace["endpoint_chord_length_m"] == 0
    assert trace["endpoint_chord_scale_only_interval_m"] == [0.0, 0.0]
    assert trace["geometric_detour_ratio"] is None
    assert "surface_trace_zero_endpoint_chord" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_direct_trace_zero_edge_has_unknown_turn_not_a_fabricated_zero() -> None:
    # Direct diagnostic callers can inspect degenerate imported geometry,
    # although the full preview separately rejects invalid triangle area.
    trace = mesh_surface_edge_traces(
        [(0, 0, 0), (0, 0, 0), (1, 0, 0)],
        [[0, 1, 2]],
        [[0, 1, 2]],
        0.01,
        None,
    )[0]
    assert trace["turn_angles_deg"] == [None, None, None]
    assert trace["maximum_turn_angle_deg"] is None
    assert trace["total_absolute_geometric_turn_deg"] is None
    assert "zero_length_edge_on_surface_trace" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_straight_trace_distinguishes_zero_bend_from_no_interior_turn() -> None:
    traces = mesh_surface_edge_traces(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)],
        [[0, 1, 3], [1, 2, 3]],
        [[0, 1, 2], [0, 1]],
        0.01,
        None,
    )
    straight, two_vertices = traces
    assert straight["turn_angles_deg"] == [None, 0.0, None]
    assert straight["maximum_turn_angle_deg"] == 0.0
    assert straight["total_absolute_geometric_turn_deg"] == 0.0
    assert straight["endpoint_chord_length_m"] == pytest.approx(0.02)
    assert straight["geometric_detour_ratio"] == pytest.approx(1.0)
    assert straight["endpoint_chord_scale_only_interval_m"] is None
    assert two_vertices["turn_angles_deg"] == [None, None]
    assert two_vertices["maximum_turn_angle_deg"] is None
    assert two_vertices["total_absolute_geometric_turn_deg"] == 0.0


@pytest.mark.parametrize(
    ("paths", "expected_status"),
    [
        ([[0]], 422),
        ([[0, 0]], 422),
        ([[0, 1, 0]], 422),
        ([[0, 3]], 400),
        ([[True, 1]], 422),
        ([[-1, 2]], 422),
        ([[0, 1]] * 17, 422),
    ],
)
def test_trace_schema_or_engine_rejects_invalid_vertex_paths(
    client: TestClient, paths: list[list[int]], expected_status: int
) -> None:
    project_id = str(create_project(client, "Bad surface trace")["id"])
    params = {**PARAMS, "surface_trace_vertex_paths": paths}
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    # Pydantic shape validation is 422; domain topology validation is 400.
    assert response.status_code == expected_status, response.text


def test_selected_trace_requires_real_triangle_edges(client: TestClient) -> None:
    project_id = str(create_project(client, "Disconnected surface trace")["id"])
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0]],
        "surface_trace_vertex_paths": [[0, 3]],
    }
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "Consecutive surface trace vertices must share a triangle edge"
    )


@pytest.mark.parametrize(
    "unreferenced_vertex",
    [
        (True, 0, 0),
        ("1", 0, 0),
        (float("nan"), 0, 0),
        (float("inf"), 0, 0),
        (10**400, 0, 0),
        (0, 0),
        None,
    ],
)
def test_direct_trace_rejects_invalid_unused_source_vertices(
    unreferenced_vertex: object,
) -> None:
    # Even vertices not used by the selected edge must pass the same numeric
    # integrity checks as the public preview API; no partial QC bypass.
    points = cast(
        list[tuple[float, float, float]],
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), unreferenced_vertex],
    )
    with pytest.raises(ValueError, match="Surface trace vertices require three finite"):
        mesh_surface_edge_traces(points, [[0, 1, 2]], [[0, 1]], 0.01, 0.1)


@pytest.mark.parametrize(
    ("scale", "uncertainty"),
    [
        (True, 0.1),
        ("1", 0.1),
        (10**400, None),
        (0.01, True),
        (0.01, "0.1"),
        (0.01, 10**400),
        (0.01, float("nan")),
        (0.01, float("inf")),
    ],
)
def test_direct_trace_calibration_rejects_coercion_and_overflow(
    scale: object, uncertainty: object
) -> None:
    # Direct scientific callers cannot interpret booleans as physical units
    # or propagate OverflowError before the measurement is reviewed.
    with pytest.raises(ValueError, match="Surface trace calibration must be finite"):
        mesh_surface_edge_traces(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            [[0, 1, 2]],
            [[0, 1]],
            cast(float, scale),
            cast(float | None, uncertainty),
        )


def test_direct_trace_identifies_duplicate_faces_without_overriding_mesh_rejection() -> None:
    # The full preview must reject duplicated triangle geometry rather than
    # saving a misleading measurement. Direct trace QC remains descriptive.
    trace = mesh_surface_edge_traces(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
        [[0, 1, 2], [2, 1, 0]],
        [[0, 1]],
        0.01,
        0.1,
    )[0]
    assert "duplicate_triangle_on_surface_trace" in trace["qc_warnings"]
    assert "inconsistent_winding_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    with pytest.raises(ValueError, match="Duplicate triangle"):
        measure_mesh_preview(**DUPLICATE_FACE_PARAMS)


def test_selected_trace_flags_inconsistent_winding_without_false_duplicate() -> None:
    trace = measure_mesh_preview(**INCONSISTENT_WINDING_PARAMS)["surface_edge_traces"][0]
    assert "inconsistent_winding_edge_on_surface_trace" in trace["qc_warnings"]
    assert "duplicate_triangle_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_trace_flags_nonadjacent_spatially_coincident_vertices() -> None:
    trace = measure_mesh_preview(**COINCIDENT_NONADJACENT_PARAMS)["surface_edge_traces"][0]
    assert trace["vertex_indices"] == [0, 1, 2]
    assert trace["segment_lengths_m"] == pytest.approx([0.01, 0.01])
    assert trace["length_m"] == pytest.approx(0.02)
    assert "nonadjacent_coincident_surface_trace_vertices" in trace["qc_warnings"]
    assert "zero_length_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_trace_flags_full_geometric_reversal_without_repeated_vertices() -> None:
    trace = measure_mesh_preview(**REVERSE_TURN_PARAMS)["surface_edge_traces"][0]
    assert trace["vertex_indices"] == [0, 1, 2]
    assert trace["segment_lengths_m"] == pytest.approx([0.02, 0.01])
    assert trace["length_m"] == pytest.approx(0.03)
    assert trace["endpoint_chord_length_m"] == pytest.approx(0.01)
    assert trace["geometric_detour_ratio"] == pytest.approx(3.0)
    assert trace["turn_angles_deg"] == [None, 180.0, None]
    assert "surface_trace_180_degree_geometric_turn" in trace["qc_warnings"]
    assert "nonadjacent_coincident_surface_trace_vertices" not in trace["qc_warnings"]
    assert "zero_length_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_trace_flags_positive_segment_lost_in_cumulative_distance() -> None:
    trace = measure_mesh_preview(**RESOLUTION_LIMITED_PARAMS)["surface_edge_traces"][0]
    assert trace["segment_lengths_m"][1] > 0
    assert trace["cumulative_lengths_m"][1] == trace["cumulative_lengths_m"][2]
    assert trace["length_m"] == pytest.approx(0.01)
    assert "surface_trace_cumulative_distance_resolution_loss" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_omitted_trace_does_not_invent_anatomical_centerlines() -> None:
    params = {key: value for key, value in PARAMS.items() if key != "surface_trace_vertex_paths"}
    result = measure_mesh_preview(**params)
    assert result["surface_edge_traces"] is None


@pytest.mark.parametrize("uncertainty", [None, 0.0, 1.0])
def test_trace_scale_boundary_is_explicit_and_not_a_confidence_interval(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(**{**PARAMS, "relative_scale_uncertainty": uncertainty})
    trace = result["surface_edge_traces"][0]
    expected = (1 + sqrt(2)) * 0.01
    assert trace["length_scale_only_interval_m"] == (
        pytest.approx([expected * (1 - uncertainty), expected * (1 + uncertainty)])
        if uncertainty is not None
        else None
    )
    for bound_key, values in (
        ("segment_length_scale_only_intervals_m", trace["segment_lengths_m"]),
        ("cumulative_length_scale_only_intervals_m", trace["cumulative_lengths_m"]),
    ):
        bounds = trace[bound_key]
        if uncertainty is None:
            assert bounds is None
        else:
            assert len(bounds) == len(values)
            for nominal, (lower, upper) in zip(values, bounds, strict=True):
                assert lower == pytest.approx(nominal * (1 - uncertainty))
                assert upper == pytest.approx(nominal * (1 + uncertainty))
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize(
    "case",
    [
        "ordinary",
        "resolution_limited",
        "inconsistent_winding",
        "coincident_nonadjacent",
        "reverse_turn",
        "uncertainty_missing",
        "uncertainty_max",
    ],
)
def test_saved_typed_mesh_trace_matches_standalone_and_provenance(
    client: TestClient, case: str
) -> None:
    project_id = str(create_project(client, "Surface edge trace workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "ordinary": PARAMS,
        "resolution_limited": RESOLUTION_LIMITED_PARAMS,
        "inconsistent_winding": INCONSISTENT_WINDING_PARAMS,
        "coincident_nonadjacent": COINCIDENT_NONADJACENT_PARAMS,
        "reverse_turn": REVERSE_TURN_PARAMS,
        "uncertainty_missing": {**PARAMS, "relative_scale_uncertainty": None},
        "uncertainty_max": {**PARAMS, "relative_scale_uncertainty": 1.0},
    }[case]
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text

    graph = {
        "graph_id": "mesh-surface-traces-v14",
        "name": "Provisional scientist-selected triangle edge trace",
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["surface_trace_vertex_paths"]
        == params["surface_trace_vertex_paths"]
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
    assert artifact["surface_edge_traces"] == standalone.json()["surface_edge_traces"]
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    trace = artifact["surface_edge_traces"][0]
    assert trace["human_review_verified"] is False
    assert "endpoint_chord_length_m" in trace
    assert "geometric_detour_ratio" in trace
    assert len(trace["turn_angles_deg"]) == len(trace["vertex_indices"])
    assert trace["turn_angles_deg"][0] is None
    assert trace["turn_angles_deg"][-1] is None
    if case == "ordinary":
        assert trace["geometric_detour_ratio"] == pytest.approx(1 + sqrt(2))
        assert trace["endpoint_chord_length_m"] == pytest.approx(0.01)
        assert trace["maximum_turn_angle_deg"] == pytest.approx(135.0)
        assert trace["total_absolute_geometric_turn_deg"] == pytest.approx(135.0)
    if case == "uncertainty_missing":
        assert trace["endpoint_chord_scale_only_interval_m"] is None
        assert trace["segment_length_scale_only_intervals_m"] is None
        assert trace["cumulative_length_scale_only_intervals_m"] is None
    else:
        assert len(trace["segment_length_scale_only_intervals_m"]) == trace["edge_count"]
        assert len(trace["cumulative_length_scale_only_intervals_m"]) == (trace["edge_count"] + 1)
    if case == "uncertainty_max":
        assert trace["cumulative_length_scale_only_intervals_m"][-1] == pytest.approx(
            [0.0, 2 * trace["length_m"]]
        )
    if case == "resolution_limited":
        assert (
            "surface_trace_cumulative_distance_resolution_loss"
            in artifact["surface_edge_traces"][0]["qc_warnings"]
        )
    if case == "inconsistent_winding":
        assert (
            "inconsistent_winding_edge_on_surface_trace"
            in artifact["surface_edge_traces"][0]["qc_warnings"]
        )
    if case == "reverse_turn":
        assert trace["maximum_turn_angle_deg"] == pytest.approx(180.0)
        assert "surface_trace_180_degree_geometric_turn" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "coincident_nonadjacent":
        assert trace["geometric_detour_ratio"] is None
        assert "surface_trace_zero_endpoint_chord" in trace["qc_warnings"]
        assert (
            "nonadjacent_coincident_surface_trace_vertices"
            in artifact["surface_edge_traces"][0]["qc_warnings"]
        )
