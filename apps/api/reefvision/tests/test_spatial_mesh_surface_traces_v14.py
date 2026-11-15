"""Caller-selected triangle-edge traces: provisional geometry and saved-workflow parity."""

from __future__ import annotations

from itertools import pairwise
from math import pi, sqrt
from typing import Any, cast

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

# Closed edge loops are selected mesh geometry, not inferred polyp contours
# or biological branch measurements. A return to vertex zero is intentional.
CLOSED_LOOP_PARAMS = {
    **PARAMS,
    "surface_trace_vertex_paths": [[0, 1, 2, 0]],
}

# A closed triangle in the YZ plane checks a 3D footprint, not just XY.
NON_XY_PLANAR_CLOSED_LOOP_PARAMS = {
    **CLOSED_LOOP_PARAMS,
    "vertices": [[0, 0, 0], [0, 2, 0], [0, 0, 3]],
    "surface_trace_vertex_paths": [[0, 1, 2, 0]],
    "relative_scale_uncertainty": 1.0,
}


# Four noncoplanar source waypoints form a valid closed tetrahedral edge loop.
# Its perimeter remains measurable, but it must never imply a planar contour
# or a scientifically verified coral cross-sectional area.
NONCOPLANAR_CLOSED_LOOP_PARAMS = {
    **PARAMS,
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "faces": [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
    "surface_trace_vertex_paths": [[0, 1, 2, 3, 0]],
}

# A source-planar bow-tie is built from valid indexed triangle edges.
# Its two nonadjacent perimeter segments cross in their interiors; the
# perimeter alone must not be treated as a biological cross-section.
PROPER_CROSSING_CLOSED_LOOP_PARAMS = {
    **PARAMS,
    "vertices": [[-1, -1, 0], [1, 1, 0], [-1, 1, 0], [1, -1, 0]],
    "faces": [[0, 1, 2], [0, 2, 3]],
    "surface_trace_vertex_paths": [[0, 1, 2, 3, 0]],
}

# A planar edge selection can have positive-length overlap and endpoint
# contacts without reusing indexed vertices or duplicating source triangles.
# These are provisional source-geometry diagnostics, not contour certification.
CONTACT_OVERLAP_CLOSED_LOOP_PARAMS = {
    **PARAMS,
    "vertices": [
        [0, 0, 0],
        [4, 0, 0],
        [4, 2, 0],
        [1, 2, 0],
        [1, 0, 0],
        [3, 0, 0],
        [3, -1, 0],
        [0, -1, 0],
    ],
    "faces": [[0, 1, 2], [2, 3, 4], [4, 5, 6], [6, 7, 0]],
    "surface_trace_vertex_paths": [[0, 1, 2, 3, 4, 5, 6, 7, 0]],
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
# Three nonduplicate triangular faces meet at the selected indexed edge,
# so the face-incidence count must expose the actual nonmanifold segment.
NONMANIFOLD_EDGE_PARAMS = {
    **PARAMS,
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]],
    "faces": [[0, 1, 2], [1, 0, 3], [0, 1, 4]],
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

# Imported OBJ/PLY-style seam vertices have different indices but identical
# XYZ endpoints. These nonduplicate triangles permit either same-direction or
# reverse traversal of the same real geometric edge during one ordered trace.
REUSED_GEOMETRIC_SEGMENT_PARAMS = {
    **PARAMS,
    "vertices": [
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 0, 0],
        [1, 0, 0],
        [0, 0, 1],
        [2, 0, 1],
        [0, 1, 1],
        [0, -1, 1],
        [1, 1, 1],
    ],
    "faces": [[0, 1, 5], [1, 2, 6], [2, 3, 7], [2, 4, 9], [3, 4, 8]],
    "surface_trace_vertex_paths": [[0, 1, 2, 3, 4]],
}


# Two separately indexed triangles share the same physical XYZ edge. An
# OBJ/PLY/GLB split-vertex seam must remain provisional and detectable
# without welding distinct source IDs or fabricating mesh connectivity.
GEOMETRIC_SEAM_PARAMS = {
    **PARAMS,
    "vertices": [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 0],
        [1, 0, 0],
        [0, -1, 0],
    ],
    "faces": [[0, 1, 2], [4, 3, 5]],
    "surface_trace_vertex_paths": [[0, 1, 2]],
}


# These faces share a geometric edge only: original indices remain split.
# Both wind that XYZ edge in the same direction, unlike the valid reversed
# orientation in GEOMETRIC_SEAM_PARAMS. Neither is a reviewed anatomy label.
GEOMETRIC_WINDING_SEAM_PARAMS = {
    **GEOMETRIC_SEAM_PARAMS,
    "faces": [[0, 1, 2], [3, 4, 5]],
}


# Three distinct triangles meet at one exact geometric XYZ edge, but use
# different original vertex IDs. Indexed topology sees only one incident
# face on the selected edge, concealing a geometric nonmanifold junction.
GEOMETRIC_NONMANIFOLD_SEAM_PARAMS = {
    **PARAMS,
    "vertices": [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 0],
        [1, 0, 0],
        [0, -1, 0],
        [0, 0, 0],
        [1, 0, 0],
        [0, 0, 1],
    ],
    "faces": [[0, 1, 2], [4, 3, 5], [6, 7, 8]],
    "surface_trace_vertex_paths": [[0, 1]],
}


# Source endpoints are separated by one representable binary64 step, but
# independently scaling their absolute coordinates erases that separation.
# The full mesh has positive area, so API and persisted graph can execute.
DISPLAY_CHORD_ROUNDING_PARAMS = {
    **PARAMS,
    "vertices": [
        [100.0, 0.0, 0.0],
        [101.0, 0.0, 0.0],
        [100.00000000000001, 0.0, 0.0],
        [100.0, 2.0, 0.0],
        [101.0, 2.0, 0.0],
    ],
    "faces": [[0, 1, 3], [1, 2, 4]],
    "meters_per_unit": 1e-100,
    "surface_trace_vertex_paths": [[0, 1, 2]],
}

# The first real indexed edge has a positive calibrated length, but separately
# scaled absolute positions round to the same displayed point. This is a
# preview-representation defect, distinct from an edge-length underflow.
DISPLAY_SEGMENT_ROUNDING_PARAMS = {
    **PARAMS,
    "vertices": [[100.0, 0, 0], [100.00000000000001, 0, 0], [100.0, 2, 0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 1e-100,
    "surface_trace_vertex_paths": [[0, 1, 2]],
}


# Source endpoint separation is real and has a finite source-frame detour
# ratio, although its scaled meter chord underflows. The triangulated mesh
# remains nondegenerate and calibrated area is representable: this exercises
# the full standalone preview and a persisted Workflow Builder graph.
FINITE_DETOUR_CHORD_UNDERFLOW_PARAMS = {
    **PARAMS,
    "vertices": [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1e-250, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ],
    "faces": [[0, 1, 3], [1, 2, 3]],
    "meters_per_unit": 1e-100,
    "surface_path_vertex_pairs": None,
    "surface_trace_vertex_paths": [[0, 1, 2]],
}

# An almost-zero imported surface edge underflows after calibration, while
# another mesh triangle keeps the full preview's area physically representable.
# The direct API and persisted typed graph must both withhold false-zero bounds.
SEGMENT_UNDERFLOW_PREVIEW_PARAMS = {
    **PARAMS,
    "vertices": [[0.0, 0.0, 0.0], [1e-250, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
    "faces": [[0, 1, 2], [0, 2, 3]],
    "meters_per_unit": 1e-100,
    "surface_path_vertex_pairs": None,
    "surface_trace_vertex_paths": [[0, 1]],
}


@pytest.mark.parametrize(
    ("params", "counts", "boundary", "nonmanifold", "duplicate", "winding"),
    [
        (PARAMS, [1, 1], [0, 1], [], [], []),
        (INCONSISTENT_WINDING_PARAMS, [2], [], [], [], [0]),
        (NONMANIFOLD_EDGE_PARAMS, [3], [], [0], [], []),
    ],
)
def test_selected_trace_locates_indexed_face_topology_for_review(
    params: dict[str, Any],
    counts: list[int],
    boundary: list[int],
    nonmanifold: list[int],
    duplicate: list[int],
    winding: list[int],
) -> None:
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    assert trace["mesh_edge_face_incidence_counts"] == counts
    assert trace["open_boundary_segment_indices"] == boundary
    assert trace["nonmanifold_segment_indices"] == nonmanifold
    assert trace["duplicate_triangle_segment_indices"] == duplicate
    assert trace["inconsistent_winding_segment_indices"] == winding
    assert len(counts) == trace["edge_count"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


@pytest.mark.parametrize(
    ("variant", "expected_error", "indexed_duplicate"),
    [
        ("reversed-indexed", "Duplicate triangles would double-count surface area", True),
        ("same-indexed", "Duplicate triangles would double-count surface area", True),
        ("split-geometry", "Duplicate triangle geometry would double-count surface area", False),
    ],
)
def test_duplicate_face_qc_is_direct_engine_only_and_preview_rejects_it(
    client: TestClient,
    variant: str,
    expected_error: str,
    indexed_duplicate: bool,
) -> None:
    # Indexed duplication (same or reversed winding) and split-vertex
    # coordinate duplication are distinct ways to double-count mesh area.
    # The direct edge helper is diagnostic, but public previews must reject
    # both, including saved executable workflows.
    params = DUPLICATE_FACE_PARAMS
    if variant == "same-indexed":
        params = {**params, "faces": [[0, 1, 2], [0, 1, 2]]}
    elif variant == "split-geometry":
        params = {
            **params,
            "vertices": [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
            ],
            "faces": [[0, 1, 2], [5, 4, 3]],
        }
    trace = mesh_surface_edge_traces(
        [tuple(vertex) for vertex in params["vertices"]],
        params["faces"],
        params["surface_trace_vertex_paths"],
        params["meters_per_unit"],
        params["relative_scale_uncertainty"],
    )[0]
    assert trace["mesh_edge_face_incidence_counts"] == ([2] if indexed_duplicate else [1])
    assert trace["duplicate_triangle_segment_indices"] == ([0] if indexed_duplicate else [])
    if indexed_duplicate:
        assert "duplicate_triangle_on_surface_trace" in trace["qc_warnings"]
    else:
        # Two separate vertex-ID sets share one real coordinate-space edge.
        # Indexed topology alone must not be mistaken for whole-mesh validity.
        assert trace["geometric_edge_face_incidence_counts"] == [2]
        assert trace["split_vertex_seam_segment_indices"] == [0]
    assert trace["human_review_verified"] is False
    with pytest.raises(ValueError, match=expected_error):
        measure_mesh_preview(**params)

    project_id = str(create_project(client, f"Invalid duplicated mesh {variant}")["id"])
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 400
    assert expected_error in response.text

    # Parameters may be saved for reproducibility, but the persisted typed
    # workflow must not generate scientifically invalid surface-area evidence.
    graph = {
        "graph_id": f"rejected-duplicate-{variant}-preview-v14",
        "name": f"Duplicate-face validation regression: {variant}",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": params,
            },
        ],
        "edges": [
            {
                "edge_id": "project-to-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
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
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


@pytest.mark.parametrize("scale", [0.01, 1.0])
@pytest.mark.parametrize("conflicting", [False, True])
def test_split_vertex_seam_reports_hidden_winding_conflict_only_when_present(
    scale: float, conflicting: bool
) -> None:
    params = {
        **(GEOMETRIC_WINDING_SEAM_PARAMS if conflicting else GEOMETRIC_SEAM_PARAMS),
        "meters_per_unit": scale,
    }
    preview = measure_mesh_preview(**params)
    trace = preview["surface_edge_traces"][0]
    assert trace["mesh_edge_face_incidence_counts"] == [1, 1]
    assert trace["geometric_edge_face_incidence_counts"] == [2, 1]
    assert trace["split_vertex_seam_segment_indices"] == [0]
    assert trace["split_vertex_winding_segment_indices"] == ([0] if conflicting else [])
    assert trace["inconsistent_winding_segment_indices"] == []
    assert trace["split_vertex_nonmanifold_segment_indices"] == []
    assert (
        "split_vertex_hidden_winding_conflict_on_surface_trace" in trace["qc_warnings"]
    ) is conflicting
    assert preview["surface_area_m2"] == pytest.approx(scale * scale)
    assert preview["provenance"]["calibration_verified"] is False
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize("shared_indexed_edge", [False, True])
@pytest.mark.parametrize("scale", [0.01, 1.0])
def test_split_vertex_seam_cannot_hide_geometric_nonmanifold_junction(
    shared_indexed_edge: bool, scale: float
) -> None:
    params = {
        **GEOMETRIC_NONMANIFOLD_SEAM_PARAMS,
        "meters_per_unit": scale,
    }
    if shared_indexed_edge:
        # Two faces really share indexed [0, 1]; the third remains split.
        params["faces"] = [[0, 1, 2], [1, 0, 5], [6, 7, 8]]
    preview = measure_mesh_preview(**params)
    trace = preview["surface_edge_traces"][0]
    assert trace["mesh_edge_face_incidence_counts"] == [2 if shared_indexed_edge else 1]
    assert trace["geometric_edge_face_incidence_counts"] == [3]
    assert trace["nonmanifold_segment_indices"] == []
    assert trace["split_vertex_nonmanifold_segment_indices"] == [0]
    assert trace["split_vertex_seam_segment_indices"] == [0]
    assert "split_vertex_hidden_nonmanifold_on_surface_trace" in trace["qc_warnings"]
    assert "nonmanifold_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["segment_lengths_m"] == pytest.approx([scale])
    assert preview["surface_area_m2"] == pytest.approx(1.5 * scale * scale)
    assert preview["provenance"]["calibration_verified"] is False
    assert trace["human_review_verified"] is False


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
    assert trace["source_segment_lengths_mesh_units"] == pytest.approx([1.0, sqrt(2)])
    assert trace["source_trace_length_mesh_units"] == pytest.approx(1 + sqrt(2))
    assert trace["source_endpoint_chord_mesh_units"] == pytest.approx(1.0)
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


@pytest.mark.parametrize(
    "path",
    [[0, 1, 2, 0], [0, 2, 1, 0], [1, 2, 0, 1]],
)
def test_simple_planar_footprint_is_scale_qualified_and_order_invariant(
    path: list[int],
) -> None:
    # A planar footprint is not 3D mesh surface area or a coral section.
    params = {**CLOSED_LOOP_PARAMS, "surface_trace_vertex_paths": [path]}
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] == pytest.approx(0.5)
    assert trace["closed_loop_planar_enclosed_area_m2"] == pytest.approx(0.00005)
    assert trace["closed_loop_planar_enclosed_area_scale_only_interval_m2"] == pytest.approx(
        [0.0000405, 0.0000605]
    )
    # Independent source-polygon reference for a right isosceles triangle.
    # Compactness is 4*pi*A/P^2, independent of calibration and path winding.
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] == pytest.approx(
        2 * pi / (2 + sqrt(2)) ** 2
    )
    assert trace["human_review_verified"] is False


def test_planar_footprint_non_xy_plane_and_full_scale_uncertainty() -> None:
    trace = measure_mesh_preview(**NON_XY_PLANAR_CLOSED_LOOP_PARAMS)["surface_edge_traces"][0]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] == pytest.approx(3.0)
    assert trace["closed_loop_planar_enclosed_area_m2"] == pytest.approx(0.0003)
    assert trace["closed_loop_planar_enclosed_area_scale_only_interval_m2"] == pytest.approx(
        [0.0, 0.0012]
    )
    # The non-XY triangle has area 3 and source perimeter 5 + sqrt(13).
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] == pytest.approx(
        12 * pi / (5 + sqrt(13)) ** 2
    )
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize(
    "params",
    [
        PARAMS,
        NONCOPLANAR_CLOSED_LOOP_PARAMS,
        PROPER_CROSSING_CLOSED_LOOP_PARAMS,
        CONTACT_OVERLAP_CLOSED_LOOP_PARAMS,
    ],
)
def test_non_simple_or_open_loops_never_have_planar_footprint(
    params: dict[str, Any],
) -> None:
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] is None
    assert trace["closed_loop_planar_enclosed_area_m2"] is None
    assert trace["closed_loop_planar_enclosed_area_scale_only_interval_m2"] is None
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None


def test_planar_area_underflow_is_unknown_not_numeric_zero() -> None:
    vertices = [(0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (0.0, 1e-200, 0.0)]
    source = mesh_surface_edge_traces(vertices, [[0, 1, 2]], [[0, 1, 2, 0]], 1.0, 0.1)[0]
    assert source["closed_loop_source_is_simple_planar_perimeter"] is True
    assert source["closed_loop_source_planar_enclosed_area_mesh_units2"] is None
    assert source["closed_loop_planar_enclosed_area_m2"] is None
    assert source["closed_loop_source_planar_isoperimetric_quotient"] is None
    assert "closed_surface_trace_source_planar_area_unrepresentable" in source["qc_warnings"]

    ordinary = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    calibrated = mesh_surface_edge_traces(ordinary, [[0, 1, 2]], [[0, 1, 2, 0]], 1e-200, 0.1)[0]
    assert calibrated["closed_loop_source_planar_enclosed_area_mesh_units2"] == 0.5
    assert calibrated["closed_loop_planar_enclosed_area_m2"] is None
    assert calibrated["closed_loop_planar_enclosed_area_scale_only_interval_m2"] is None
    assert (
        "closed_surface_trace_calibrated_planar_area_unrepresentable" in calibrated["qc_warnings"]
    )


@pytest.mark.parametrize("scale", [0.01, 0.02])
def test_closed_surface_loop_measures_perimeter_once_with_a_unique_closure_turn(
    scale: float,
) -> None:
    result = measure_mesh_preview(**{**CLOSED_LOOP_PARAMS, "meters_per_unit": scale})
    trace = result["surface_edge_traces"][0]
    assert trace["is_closed_surface_loop"] is True
    assert trace["closed_loop_source_exact_coplanarity"] is True
    assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == []
    assert trace["closed_loop_source_proper_crossing_segment_pairs"] == []
    assert trace["vertex_indices"] == [0, 1, 2, 0]
    assert trace["edge_count"] == 3
    assert trace["segment_lengths_m"] == pytest.approx([scale, sqrt(2) * scale, scale])
    assert trace["length_m"] == pytest.approx((2 + sqrt(2)) * scale)
    assert trace["turn_angles_deg"][:3] == pytest.approx([90.0, 135.0, 135.0])
    assert trace["turn_angles_deg"][-1] is None
    assert trace["maximum_turn_angle_deg"] == pytest.approx(135.0)
    assert trace["total_absolute_geometric_turn_deg"] == pytest.approx(360.0)
    assert trace["source_endpoint_chord_mesh_units"] == 0.0
    assert trace["geometric_detour_ratio"] is None
    assert trace["nonadjacent_coincident_waypoint_index_pairs"] == []
    assert trace["repeated_geometric_segment_index_pairs"] == []
    assert "closed_surface_trace_not_verified_anatomical_contour" in trace["qc_warnings"]
    assert "surface_trace_zero_endpoint_chord" in trace["qc_warnings"]
    assert "nonadjacent_coincident_surface_trace_vertices" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


@pytest.mark.parametrize(
    "path",
    [[0, 2, 1, 0], [1, 2, 0, 1], [2, 0, 1, 2]],
)
def test_closed_surface_loop_perimeter_is_winding_and_start_invariant(
    path: list[int],
) -> None:
    # Reversing winding or rotating the first waypoint must not change a
    # closed loop's metric perimeter, marginal scale interval, or one-turn-
    # per-corner total. These are geometry-only, not anatomical identities.
    reference = measure_mesh_preview(**CLOSED_LOOP_PARAMS)["surface_edge_traces"][0]
    candidate = measure_mesh_preview(
        **{**CLOSED_LOOP_PARAMS, "surface_trace_vertex_paths": [path]}
    )["surface_edge_traces"][0]
    assert candidate["vertex_indices"] == path
    assert candidate["is_closed_surface_loop"] is True
    assert candidate["edge_count"] == 3
    assert candidate["length_m"] == pytest.approx(reference["length_m"])
    assert candidate["source_trace_length_mesh_units"] == pytest.approx(
        reference["source_trace_length_mesh_units"]
    )
    assert candidate["length_scale_only_interval_m"] == pytest.approx(
        reference["length_scale_only_interval_m"]
    )
    geometric_turns = sorted(angle for angle in candidate["turn_angles_deg"] if angle is not None)
    assert geometric_turns == pytest.approx([90.0, 135.0, 135.0])
    assert candidate["turn_angles_deg"][-1] is None
    assert candidate["total_absolute_geometric_turn_deg"] == pytest.approx(360.0)
    assert candidate["source_endpoint_chord_mesh_units"] == 0.0
    assert candidate["geometric_detour_ratio"] is None
    assert candidate["nonadjacent_coincident_waypoint_index_pairs"] == []
    assert candidate["repeated_geometric_segment_index_pairs"] == []
    assert "closed_surface_trace_not_verified_anatomical_contour" in candidate["qc_warnings"]
    assert candidate["human_review_verified"] is False


@pytest.mark.parametrize(
    "path",
    [[0, 1, 2, 3, 0], [0, 3, 2, 1, 0], [1, 2, 3, 0, 1]],
)
def test_closed_trace_exact_xyz_planarity_audit_is_order_invariant(
    path: list[int],
) -> None:
    trace = measure_mesh_preview(
        **{
            **NONCOPLANAR_CLOSED_LOOP_PARAMS,
            "surface_trace_vertex_paths": [path],
        }
    )["surface_edge_traces"][0]
    assert trace["is_closed_surface_loop"] is True
    assert trace["closed_loop_source_exact_coplanarity"] is False
    assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == [3]
    assert trace["closed_loop_source_proper_crossing_segment_pairs"] is None
    assert "closed_surface_trace_exact_source_noncoplanarity" in trace["qc_warnings"]
    assert "closed_surface_trace_not_verified_anatomical_contour" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


@pytest.mark.parametrize(
    ("path", "expected_pairs"),
    [
        ([0, 1, 2, 3, 0], [[0, 2]]),
        ([0, 3, 2, 1, 0], [[1, 3]]),
        ([1, 2, 3, 0, 1], [[1, 3]]),
    ],
)
def test_exact_planar_loop_reports_proper_source_segment_crossings(
    path: list[int], expected_pairs: list[list[int]]
) -> None:
    trace = measure_mesh_preview(
        **{
            **PROPER_CROSSING_CLOSED_LOOP_PARAMS,
            "surface_trace_vertex_paths": [path],
        }
    )["surface_edge_traces"][0]
    assert trace["is_closed_surface_loop"] is True
    assert trace["closed_loop_source_exact_coplanarity"] is True
    assert trace["closed_loop_source_proper_crossing_segment_pairs"] == expected_pairs
    assert "closed_surface_trace_source_proper_self_intersection" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_proper_source_crossing_audit_uses_non_xy_reference_plane() -> None:
    # Every vertex has constant X. Projection to YZ must retain the crossing.
    points = [
        (0.0, float(x), float(y)) for x, y, _ in PROPER_CROSSING_CLOSED_LOOP_PARAMS["vertices"]
    ]
    traces = mesh_surface_edge_traces(
        points=points,
        faces=PROPER_CROSSING_CLOSED_LOOP_PARAMS["faces"],
        vertex_paths=[[0, 1, 2, 3, 0]],
        scale=0.01,
        scale_uncertainty=0.1,
    )
    assert traces is not None
    assert traces[0]["closed_loop_source_exact_coplanarity"] is True
    assert traces[0]["closed_loop_source_proper_crossing_segment_pairs"] == [[0, 2]]


@pytest.mark.parametrize("scale", [0.01, 0.02])
def test_closed_trace_reports_exact_collinear_overlap_and_nonadjacent_contacts(
    scale: float,
) -> None:
    trace = measure_mesh_preview(
        **{**CONTACT_OVERLAP_CLOSED_LOOP_PARAMS, "meters_per_unit": scale}
    )["surface_edge_traces"][0]
    assert trace["closed_loop_source_exact_coplanarity"] is True
    assert trace["closed_loop_source_proper_crossing_segment_pairs"] == []
    assert trace["closed_loop_source_collinear_overlap_segment_pairs"] == [[0, 4]]
    assert trace["closed_loop_source_touching_segment_pairs"] == [[0, 3], [0, 5]]
    warnings = trace["qc_warnings"]
    assert "closed_surface_trace_source_collinear_segment_overlap" in warnings
    assert "closed_surface_trace_source_nonadjacent_segment_contact" in warnings
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_closed_trace_collinear_source_waypoints_have_undefined_reference_plane() -> None:
    # Direct engine only: overlapping faces are intentionally unsuitable for
    # public calibrated area preview. No arbitrary planar-fit tolerance is used.
    traces = mesh_surface_edge_traces(
        points=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ],
        faces=[[0, 1, 3], [1, 2, 3], [2, 0, 3]],
        vertex_paths=[[0, 1, 2, 0]],
        scale=0.01,
        scale_uncertainty=0.1,
    )
    assert traces is not None
    trace = traces[0]
    assert trace["closed_loop_source_exact_coplanarity"] is None
    assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == []
    assert trace["closed_loop_source_proper_crossing_segment_pairs"] is None
    assert trace["closed_loop_source_touching_segment_pairs"] is None
    assert trace["closed_loop_source_collinear_overlap_segment_pairs"] is None
    assert "closed_surface_trace_source_reference_plane_undefined" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


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
    assert (
        first["source_segment_lengths_mesh_units"] == rescaled["source_segment_lengths_mesh_units"]
    )
    assert first["source_trace_length_mesh_units"] == rescaled["source_trace_length_mesh_units"]
    assert first["source_endpoint_chord_mesh_units"] == rescaled["source_endpoint_chord_mesh_units"]


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


@pytest.mark.parametrize(
    ("vertex_path", "expected_pairs", "expected_reuse"),
    [
        ([0, 1, 2, 3, 4], [[0, 3]], 1.0),
        ([0, 1, 2, 4, 3], [[1, 2], [0, 3]], 2.0),
    ],
)
def test_seam_vertex_aliases_cannot_hide_reused_surface_trace_segment(
    vertex_path: list[int], expected_pairs: list[list[int]], expected_reuse: float
) -> None:
    params = {
        **REUSED_GEOMETRIC_SEGMENT_PARAMS,
        "surface_trace_vertex_paths": [vertex_path],
    }
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    assert trace["vertex_indices"] == vertex_path
    assert len(set(trace["vertex_indices"])) == len(vertex_path)
    assert trace["repeated_geometric_segment_index_pairs"] == expected_pairs
    assert "surface_trace_reused_geometric_segment" in trace["qc_warnings"]
    assert trace["reused_geometric_segment_source_length_mesh_units"] == pytest.approx(
        expected_reuse
    )
    assert trace["reused_geometric_segment_fraction_of_trace"] == pytest.approx(
        expected_reuse / sum(trace["source_segment_lengths_mesh_units"])
    )
    assert trace["segment_lengths_m"][0] == pytest.approx(trace["segment_lengths_m"][3])
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


@pytest.mark.parametrize("scale", [0.0001, 0.01, 2.0])
def test_reused_geometric_segment_fraction_is_calibration_invariant(scale: float) -> None:
    trace = measure_mesh_preview(**{**REUSED_GEOMETRIC_SEGMENT_PARAMS, "meters_per_unit": scale})[
        "surface_edge_traces"
    ][0]
    assert trace["reused_geometric_segment_source_length_mesh_units"] == pytest.approx(1.0)
    assert trace["reused_geometric_segment_fraction_of_trace"] == pytest.approx(1.0 / (3 + sqrt(2)))
    assert trace["human_review_verified"] is False


def test_reuse_fraction_remains_finite_with_overflowed_source_total() -> None:
    # A source-coordinate total can overflow while the exact dimensionless
    # fraction remains meaningful. Keep the measured lengths provisional.
    points = [
        (0.0, 0.0, 0.0),
        (1e308, 0.0, 0.0),
        (0.0, 1e308, 0.0),
        (0.0, 0.0, 0.0),
        (1e308, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1e308, 1.0, 0.0),
        (0.0, 1e308, 1.0),
        (0.0, -1.0, 0.0),
    ]
    trace = mesh_surface_edge_traces(
        points,
        [[0, 1, 5], [1, 2, 6], [2, 3, 7], [3, 4, 8]],
        [[0, 1, 2, 3, 4]],
        1e-308,
        0.1,
    )[0]
    assert trace["length_m"] == pytest.approx(3 + sqrt(2))
    assert trace["source_trace_length_mesh_units"] is None
    # The source total exceeds binary64, but its dimensionless endpoint
    # detour remains finite and is independent of the shared calibration.
    assert trace["geometric_detour_ratio"] == pytest.approx(3 + sqrt(2))
    assert "surface_trace_detour_ratio_unrepresentable" not in trace["qc_warnings"]
    assert trace["reused_geometric_segment_source_length_mesh_units"] == pytest.approx(1e308)
    assert trace["reused_geometric_segment_fraction_of_trace"] == pytest.approx(1 / (3 + sqrt(2)))
    fractions = trace["source_cumulative_arc_length_fractions"]
    assert fractions is not None
    assert fractions[0] == 0.0
    assert fractions[-1] == 1.0
    assert all(0 <= a < b <= 1 for a, b in pairwise(fractions))
    assert trace["source_arc_fraction_resolution_loss_segment_indices"] == []
    assert "surface_trace_source_length_unrepresentable" in trace["qc_warnings"]
    assert "surface_trace_reuse_fraction_unrepresentable" not in trace["qc_warnings"]
    assert "surface_trace_reuse_fraction_resolution_loss" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_genuinely_unrepresentable_detour_remains_null_with_explicit_qc() -> None:
    # The source total is finite, but dividing by the positive subnormal
    # endpoint chord exceeds binary64. Do not serialize infinity as evidence.
    smallest = float.fromhex("0x0.0000000000001p-1022")
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (smallest, 0.0, 0.0)],
        [[0, 1, 2]],
        [[0, 1, 2]],
        1.0,
        None,
    )[0]
    assert trace["source_trace_length_mesh_units"] == pytest.approx(2.0)
    assert trace["source_endpoint_chord_mesh_units"] == smallest
    assert trace["geometric_detour_ratio"] is None
    assert "surface_trace_detour_ratio_unrepresentable" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_reuse_fraction_flags_subnormal_source_ratio_rounding_to_zero() -> None:
    # An exact positive reused fraction may be too small for binary64. Report
    # precision loss; zero in the persisted field must not imply no reuse.
    smallest = float.fromhex("0x0.0000000000001p-1022")
    points = [
        (0.0, 0.0, 0.0),
        (smallest, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (smallest, 0.0, 0.0),
        (1e308, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    ]
    trace = mesh_surface_edge_traces(
        points,
        [[0, 1, 5], [1, 2, 6], [2, 3, 7], [3, 4, 8]],
        [[0, 1, 2, 3, 4]],
        1e-308,
        0.1,
    )[0]
    assert trace["repeated_geometric_segment_index_pairs"] == [[0, 1], [0, 2]]
    assert trace["reused_geometric_segment_source_length_mesh_units"] > 0
    assert trace["reused_geometric_segment_fraction_of_trace"] == 0.0
    assert "surface_trace_reused_geometric_segment" in trace["qc_warnings"]
    assert "surface_trace_reuse_fraction_resolution_loss" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize("conflicting_winding", [False, True])
def test_direct_trace_geometric_keys_preserve_list_and_tuple_xyz(
    conflicting_winding: bool,
) -> None:
    # The API uses JSON-style lists, while scientific Python callers may use
    # tuples. Both must produce identical seam QC without mutating raw XYZ.
    params = GEOMETRIC_WINDING_SEAM_PARAMS if conflicting_winding else GEOMETRIC_SEAM_PARAMS
    points = [list(vertex) for vertex in params["vertices"]]
    original_points = [list(vertex) for vertex in points]
    faces = [list(face) for face in params["faces"]]
    paths = [list(path) for path in params["surface_trace_vertex_paths"]]
    list_result = mesh_surface_edge_traces(points, faces, paths, 0.01, 0.1)
    tuple_result = mesh_surface_edge_traces(
        [tuple(vertex) for vertex in points], faces, paths, 0.01, 0.1
    )
    assert list_result == tuple_result
    assert list_result is not None
    trace = list_result[0]
    assert points == original_points
    assert trace["geometric_edge_face_incidence_counts"] == [2, 1]
    assert trace["split_vertex_seam_segment_indices"] == [0]
    assert trace["split_vertex_winding_segment_indices"] == ([0] if conflicting_winding else [])
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


@pytest.mark.parametrize("scale", [0.001, 0.01, 3.0])
def test_split_vertex_geometric_seam_is_localized_without_welding(scale: float) -> None:
    params = {**GEOMETRIC_SEAM_PARAMS, "meters_per_unit": scale}
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    assert trace["vertex_indices"] == [0, 1, 2]
    assert trace["mesh_edge_face_incidence_counts"] == [1, 1]
    assert trace["geometric_edge_face_incidence_counts"] == [2, 1]
    assert trace["split_vertex_seam_segment_indices"] == [0]
    assert trace["open_boundary_segment_indices"] == [0, 1]
    assert "split_vertex_geometric_seam_on_surface_trace" in trace["qc_warnings"]
    assert trace["segment_lengths_m"] == pytest.approx([scale, sqrt(2) * scale])
    assert trace["length_m"] == pytest.approx((1 + sqrt(2)) * scale)
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_shared_indexed_edge_does_not_false_flag_split_vertex_seam() -> None:
    trace = measure_mesh_preview(**INCONSISTENT_WINDING_PARAMS)["surface_edge_traces"][0]
    assert trace["mesh_edge_face_incidence_counts"] == [2]
    assert trace["geometric_edge_face_incidence_counts"] == [2]
    assert trace["split_vertex_seam_segment_indices"] == []
    assert "split_vertex_geometric_seam_on_surface_trace" not in trace["qc_warnings"]
    assert "inconsistent_winding_edge_on_surface_trace" in trace["qc_warnings"]


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
        ([[0, 1, 0, 1]], 422),
        ([[0, 1, 2, 1, 0]], 422),
        ([[0, 1, 2, 0, 0]], 422),
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


@pytest.mark.parametrize("scale", [0.01, 2.0])
def test_direct_closed_trace_detects_exact_adjacent_edge_backtrack(scale: float) -> None:
    # A deliberately selected loop doubles back along an adjacent edge, a
    # case skipped by the nonadjacent segment-intersection audit. It cannot
    # qualify as a simple planar perimeter or a verified coral contour.
    traces = mesh_surface_edge_traces(
        [(0, 0, 0), (2, 0, 0), (1, 0, 0), (1, 2, 0), (0, 2, 0)],
        [[0, 1, 3], [1, 2, 3], [0, 3, 4]],
        [[0, 1, 2, 3, 4, 0]],
        scale,
        0.1,
    )
    assert traces is not None
    trace = traces[0]
    assert trace["closed_loop_source_exact_coplanarity"] is True
    assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == [1]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is False
    assert "closed_surface_trace_source_adjacent_backtrack" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


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
    assert trace["nonadjacent_coincident_waypoint_index_pairs"] == [[0, 2]]
    assert trace["segment_lengths_m"] == pytest.approx([0.01, 0.01])
    assert trace["length_m"] == pytest.approx(0.02)
    assert "nonadjacent_coincident_surface_trace_vertices" in trace["qc_warnings"]
    assert "zero_length_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_coincident_waypoint_audit_ignores_adjacent_aliases_but_locates_distant_ones() -> None:
    # A zero-length adjacent alias and two later nonadjacent aliases are
    # distinct topological concerns. All pairs are waypoint offsets, not
    # the original mesh vertex IDs or verified biological reidentifications.
    traces = mesh_surface_edge_traces(
        [(0, 0, 0), (0, 0, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0)],
        [[0, 1, 4], [1, 2, 4], [2, 3, 4]],
        [[0, 1, 2, 3]],
        0.01,
        None,
    )
    assert traces is not None
    trace = traces[0]
    assert trace["nonadjacent_coincident_waypoint_index_pairs"] == [[0, 3], [1, 3]]
    assert "nonadjacent_coincident_surface_trace_vertices" in trace["qc_warnings"]
    assert "zero_length_edge_on_surface_trace" in trace["qc_warnings"]
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
    assert trace["nonadjacent_coincident_waypoint_index_pairs"] == []
    assert "zero_length_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False
    assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_surface_trace_source_chord_survives_calibrated_display_rounding() -> None:
    params = DISPLAY_CHORD_ROUNDING_PARAMS
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    source_chord = 100.00000000000001 - 100.0
    expected_chord_m = source_chord * params["meters_per_unit"]
    assert trace["vertices_in_source_frame_m"][0] == trace["vertices_in_source_frame_m"][-1]
    assert trace["endpoint_chord_length_m"] == pytest.approx(expected_chord_m, rel=1e-12, abs=0)
    source_route_length = 1.0 + (101.0 - 100.00000000000001)
    assert trace["geometric_detour_ratio"] == pytest.approx(
        source_route_length / source_chord, rel=1e-12
    )
    assert "surface_trace_endpoint_chord_display_coordinate_collapse" in trace["qc_warnings"]
    assert "surface_trace_zero_endpoint_chord" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_surface_trace_flags_real_segment_erased_from_display_positions() -> None:
    trace = measure_mesh_preview(**DISPLAY_SEGMENT_ROUNDING_PARAMS)["surface_edge_traces"][0]
    assert trace["segment_lengths_m"][0] > 0
    assert trace["vertices_in_source_frame_m"][0] == trace["vertices_in_source_frame_m"][1]
    assert trace["display_coordinate_collapsed_segment_indices"] == [0]
    assert "surface_trace_segment_display_coordinate_collapse" in trace["qc_warnings"]
    assert "calibrated_surface_trace_segment_underflow" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_finite_source_detour_survives_calibrated_chord_underflow() -> None:
    trace = measure_mesh_preview(**FINITE_DETOUR_CHORD_UNDERFLOW_PARAMS)["surface_edge_traces"][0]
    assert trace["length_m"] > 0
    assert trace["endpoint_chord_length_m"] == 0
    # An underflowed positive chord has no trustworthy numerical meter bound.
    # A genuinely coincident source chord, by contrast, has a [0, 0] bound.
    assert trace["endpoint_chord_scale_only_interval_m"] is None
    assert trace["geometric_detour_ratio"] == pytest.approx(2e250, rel=1e-12)
    assert "calibrated_surface_trace_endpoint_chord_underflow" in trace["qc_warnings"]
    assert "surface_trace_detour_ratio_unrepresentable" not in trace["qc_warnings"]
    assert "surface_trace_zero_endpoint_chord" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_source_geometry_survives_positive_segment_calibration_underflow() -> None:
    # Source geometry stays auditable even when meters-per-unit calibration
    # cannot represent a positive imported triangle edge in binary64 meters.
    # The raw mesh coordinates have no independently verified physical unit.
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [[0, 1, 2]],
        [[0, 1]],
        1e-200,
        0.1,
    )[0]
    assert trace["segment_lengths_m"] == [0.0]
    assert trace["length_m"] == 0.0
    assert trace["source_segment_lengths_mesh_units"] == pytest.approx([1e-200], rel=1e-12, abs=0)
    assert trace["source_trace_length_mesh_units"] == pytest.approx(1e-200, rel=1e-12, abs=0)
    assert trace["source_endpoint_chord_mesh_units"] == pytest.approx(1e-200, rel=1e-12, abs=0)
    assert trace["segment_length_scale_only_intervals_m"] is None
    assert trace["cumulative_length_scale_only_intervals_m"] is None
    assert trace["length_scale_only_interval_m"] is None
    assert "calibrated_surface_trace_segment_underflow" in trace["qc_warnings"]
    assert "calibrated_surface_trace_endpoint_chord_underflow" in trace["qc_warnings"]
    assert "calibrated_surface_trace_length_underflow" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize("scale", [1e-100, 0.01, 2.0])
def test_source_arc_fractions_preserve_tiny_waypoint_underflow_and_scale(scale: float) -> None:
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (1e-250, 0.0, 0.0), (1e-250, 1.0, 0.0)],
        [[0, 1, 2]],
        [[0, 1, 2]],
        scale,
        0.1,
    )[0]
    assert trace["source_cumulative_arc_length_fractions"] == pytest.approx(
        [0.0, 1e-250, 1.0], abs=0
    )
    assert "surface_trace_source_arc_fraction_resolution_loss" not in trace["qc_warnings"]
    assert trace["source_arc_fraction_resolution_loss_segment_indices"] == []
    assert trace["human_review_verified"] is False


def test_source_arc_fraction_resolution_loss_is_explicit_not_fabricated_progress() -> None:
    smallest = float.fromhex("0x0.0000000000001p-1022")
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (smallest, 0.0, 0.0), (smallest, 1e10, 0.0)],
        [[0, 1, 2]],
        [[0, 1, 2]],
        1e-10,
        None,
    )[0]
    assert trace["source_segment_lengths_mesh_units"][0] > 0
    assert trace["source_cumulative_arc_length_fractions"] == [0.0, 0.0, 1.0]
    assert trace["source_arc_fraction_resolution_loss_segment_indices"] == [0]
    assert "surface_trace_source_arc_fraction_resolution_loss" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize("scale", [0.01, 2.0])
def test_source_arc_fraction_localizes_late_positive_edge_roundoff(scale: float) -> None:
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1e-17, 0.0)],
        [[0, 1, 2]],
        [[0, 1, 2]],
        scale,
        0.1,
    )[0]
    assert trace["source_segment_lengths_mesh_units"][1] > 0
    assert trace["source_cumulative_arc_length_fractions"] == [0.0, 1.0, 1.0]
    assert trace["source_arc_fraction_resolution_loss_segment_indices"] == [1]
    assert "surface_trace_source_arc_fraction_resolution_loss" in trace["qc_warnings"]
    assert "zero_length_edge_on_surface_trace" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_trace_underflow_uncertainty_matches_api_without_false_zero_bounds() -> None:
    trace = measure_mesh_preview(**SEGMENT_UNDERFLOW_PREVIEW_PARAMS)["surface_edge_traces"][0]
    assert trace["source_segment_lengths_mesh_units"] == pytest.approx([1e-250], abs=0)
    assert trace["segment_lengths_m"] == [0.0]
    assert trace["length_m"] == 0.0
    assert trace["segment_length_scale_only_intervals_m"] is None
    assert trace["cumulative_length_scale_only_intervals_m"] is None
    assert trace["length_scale_only_interval_m"] is None
    assert trace["endpoint_chord_scale_only_interval_m"] is None
    assert "calibrated_surface_trace_segment_underflow" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


def test_genuinely_zero_source_trace_retains_exact_zero_intervals() -> None:
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [[0, 1, 2]],
        [[0, 1]],
        0.01,
        0.1,
    )[0]
    assert trace["source_segment_lengths_mesh_units"] == [0.0]
    assert trace["reused_geometric_segment_source_length_mesh_units"] == 0.0
    assert trace["reused_geometric_segment_fraction_of_trace"] is None
    assert trace["source_cumulative_arc_length_fractions"] is None
    assert trace["source_arc_fraction_resolution_loss_segment_indices"] == []
    assert "surface_trace_source_arc_fractions_undefined_zero_total" in trace["qc_warnings"]
    assert trace["segment_length_scale_only_intervals_m"] == [[0.0, 0.0]]
    assert trace["cumulative_length_scale_only_intervals_m"] == [
        [0.0, 0.0],
        [0.0, 0.0],
    ]
    assert trace["length_scale_only_interval_m"] == [0.0, 0.0]
    assert "calibrated_surface_trace_segment_underflow" not in trace["qc_warnings"]
    assert "zero_length_edge_on_surface_trace" in trace["qc_warnings"]


def test_surface_trace_distinguishes_calibrated_chord_underflow() -> None:
    smallest = float.fromhex("0x0.0000000000001p-1022")
    trace = mesh_surface_edge_traces(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (smallest, 0.0, 0.0)],
        [[0, 1, 2]],
        [[0, 1, 2]],
        smallest,
        None,
    )[0]
    assert trace["length_m"] > 0
    assert trace["endpoint_chord_length_m"] == 0
    assert trace["geometric_detour_ratio"] is None
    assert trace["endpoint_chord_scale_only_interval_m"] is None
    assert "surface_trace_detour_ratio_unrepresentable" in trace["qc_warnings"]
    assert "calibrated_surface_trace_endpoint_chord_underflow" in trace["qc_warnings"]
    assert "surface_trace_zero_endpoint_chord" not in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


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
        "closed_loop",
        "closed_loop_reverse",
        "closed_loop_rotated",
        "closed_loop_max_uncertainty",
        "non_xy_planar_closed_loop",
        "noncoplanar_closed_loop",
        "proper_crossing_closed_loop",
        "contact_overlap_closed_loop",
        "resolution_limited",
        "inconsistent_winding",
        "nonmanifold",
        "geometric_seam",
        "geometric_winding_seam",
        "geometric_nonmanifold_seam",
        "coincident_nonadjacent",
        "reverse_turn",
        "reused_geometric_segment",
        "display_chord_rounding",
        "display_segment_rounding",
        "uncertainty_missing",
        "uncertainty_max",
        "finite_detour_chord_underflow",
        "segment_underflow",
    ],
)
def test_saved_typed_mesh_trace_matches_standalone_and_provenance(
    client: TestClient, case: str
) -> None:
    project_id = str(create_project(client, "Surface edge trace workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "ordinary": PARAMS,
        "closed_loop": CLOSED_LOOP_PARAMS,
        "closed_loop_reverse": {
            **CLOSED_LOOP_PARAMS,
            "surface_trace_vertex_paths": [[0, 2, 1, 0]],
        },
        "closed_loop_rotated": {
            **CLOSED_LOOP_PARAMS,
            "surface_trace_vertex_paths": [[1, 2, 0, 1]],
        },
        "closed_loop_max_uncertainty": {
            **CLOSED_LOOP_PARAMS,
            "relative_scale_uncertainty": 1.0,
        },
        "non_xy_planar_closed_loop": NON_XY_PLANAR_CLOSED_LOOP_PARAMS,
        "noncoplanar_closed_loop": NONCOPLANAR_CLOSED_LOOP_PARAMS,
        "proper_crossing_closed_loop": PROPER_CROSSING_CLOSED_LOOP_PARAMS,
        "contact_overlap_closed_loop": CONTACT_OVERLAP_CLOSED_LOOP_PARAMS,
        "resolution_limited": RESOLUTION_LIMITED_PARAMS,
        "inconsistent_winding": INCONSISTENT_WINDING_PARAMS,
        "nonmanifold": NONMANIFOLD_EDGE_PARAMS,
        "geometric_seam": GEOMETRIC_SEAM_PARAMS,
        "geometric_winding_seam": GEOMETRIC_WINDING_SEAM_PARAMS,
        "geometric_nonmanifold_seam": GEOMETRIC_NONMANIFOLD_SEAM_PARAMS,
        "coincident_nonadjacent": COINCIDENT_NONADJACENT_PARAMS,
        "reverse_turn": REVERSE_TURN_PARAMS,
        "reused_geometric_segment": REUSED_GEOMETRIC_SEGMENT_PARAMS,
        "display_chord_rounding": DISPLAY_CHORD_ROUNDING_PARAMS,
        "display_segment_rounding": DISPLAY_SEGMENT_ROUNDING_PARAMS,
        "uncertainty_missing": {**PARAMS, "relative_scale_uncertainty": None},
        "uncertainty_max": {**PARAMS, "relative_scale_uncertainty": 1.0},
        "finite_detour_chord_underflow": FINITE_DETOUR_CHORD_UNDERFLOW_PARAMS,
        "segment_underflow": SEGMENT_UNDERFLOW_PREVIEW_PARAMS,
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
    assert "closed_loop_planar_enclosed_area_m2" in trace
    assert "closed_loop_source_planar_enclosed_area_mesh_units2" in trace
    assert "closed_loop_planar_enclosed_area_scale_only_interval_m2" in trace
    assert "closed_loop_source_planar_isoperimetric_quotient" in trace
    assert len(trace["source_segment_lengths_mesh_units"]) == trace["edge_count"]
    fractions = trace["source_cumulative_arc_length_fractions"]
    assert fractions is None or (
        len(fractions) == len(trace["vertex_indices"])
        and fractions[0] == 0.0
        and fractions[-1] == 1.0
        and all(0 <= a <= b <= 1 for a, b in pairwise(fractions))
    )
    loss_indices = trace["source_arc_fraction_resolution_loss_segment_indices"]
    assert all(0 <= index < trace["edge_count"] for index in loss_indices)
    assert fractions is not None or loss_indices == []
    if fractions is not None:
        assert all(
            trace["source_segment_lengths_mesh_units"][index] > 0
            and fractions[index] == fractions[index + 1]
            for index in loss_indices
        )
    if case == "ordinary":
        assert fractions == pytest.approx([0.0, 1 / (1 + sqrt(2)), 1.0])
        assert loss_indices == []
    if case == "resolution_limited":
        assert loss_indices == [1]
        assert "surface_trace_source_arc_fraction_resolution_loss" in trace["qc_warnings"]
    assert all(
        0 <= earlier < later - 1 < len(trace["vertex_indices"])
        for earlier, later in trace["nonadjacent_coincident_waypoint_index_pairs"]
    )
    assert len(trace["mesh_edge_face_incidence_counts"]) == trace["edge_count"]
    assert len(trace["geometric_edge_face_incidence_counts"]) == trace["edge_count"]
    assert all(
        geometric >= indexed
        for indexed, geometric in zip(
            trace["mesh_edge_face_incidence_counts"],
            trace["geometric_edge_face_incidence_counts"],
            strict=True,
        )
    )
    assert all(
        0 <= index < trace["edge_count"]
        for field in (
            "open_boundary_segment_indices",
            "nonmanifold_segment_indices",
            "duplicate_triangle_segment_indices",
            "inconsistent_winding_segment_indices",
            "split_vertex_seam_segment_indices",
            "split_vertex_nonmanifold_segment_indices",
            "split_vertex_winding_segment_indices",
        )
        for index in trace[field]
    )
    assert "source_endpoint_chord_mesh_units" in trace
    assert "source_trace_length_mesh_units" in trace
    assert len(trace["turn_angles_deg"]) == len(trace["vertex_indices"])
    if case in (
        "closed_loop",
        "closed_loop_reverse",
        "closed_loop_rotated",
        "closed_loop_max_uncertainty",
        "non_xy_planar_closed_loop",
        "noncoplanar_closed_loop",
        "proper_crossing_closed_loop",
        "contact_overlap_closed_loop",
    ):
        assert trace["is_closed_surface_loop"] is True
        assert trace["turn_angles_deg"][-1] is None
        if case == "noncoplanar_closed_loop":
            assert trace["closed_loop_planar_enclosed_area_m2"] is None
            assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None
            assert trace["closed_loop_source_exact_coplanarity"] is False
            assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == [3]
            assert trace["closed_loop_source_proper_crossing_segment_pairs"] is None
            assert trace["closed_loop_source_touching_segment_pairs"] is None
            assert trace["closed_loop_source_collinear_overlap_segment_pairs"] is None
            assert trace["closed_loop_source_is_simple_planar_perimeter"] is None
            assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == []
            assert "closed_surface_trace_exact_source_noncoplanarity" in trace["qc_warnings"]
        elif case == "contact_overlap_closed_loop":
            assert trace["closed_loop_planar_enclosed_area_m2"] is None
            assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None
            assert trace["closed_loop_source_exact_coplanarity"] is True
            assert trace["closed_loop_source_proper_crossing_segment_pairs"] == []
            assert trace["closed_loop_source_touching_segment_pairs"] == [[0, 3], [0, 5]]
            assert trace["closed_loop_source_collinear_overlap_segment_pairs"] == [[0, 4]]
            assert trace["closed_loop_source_is_simple_planar_perimeter"] is False
            assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == []
            assert "closed_surface_trace_source_collinear_segment_overlap" in trace["qc_warnings"]
            assert "closed_surface_trace_source_nonadjacent_segment_contact" in trace["qc_warnings"]
        elif case == "proper_crossing_closed_loop":
            assert trace["closed_loop_planar_enclosed_area_m2"] is None
            assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None
            assert trace["closed_loop_source_exact_coplanarity"] is True
            assert trace["closed_loop_source_proper_crossing_segment_pairs"] == [[0, 2]]
            assert trace["closed_loop_source_touching_segment_pairs"] == []
            assert trace["closed_loop_source_collinear_overlap_segment_pairs"] == []
            assert trace["closed_loop_source_is_simple_planar_perimeter"] is False
            assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == []
            assert "closed_surface_trace_source_proper_self_intersection" in trace["qc_warnings"]
        else:
            if case != "non_xy_planar_closed_loop":
                expected_closing_turn = 135.0 if case == "closed_loop_rotated" else 90.0
                assert trace["turn_angles_deg"][0] == pytest.approx(expected_closing_turn)
                assert trace["total_absolute_geometric_turn_deg"] == pytest.approx(360.0)
            assert trace["closed_loop_source_exact_coplanarity"] is True
            assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == []
            assert trace["closed_loop_source_proper_crossing_segment_pairs"] == []
            assert trace["closed_loop_source_touching_segment_pairs"] == []
            assert trace["closed_loop_source_collinear_overlap_segment_pairs"] == []
            assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
            assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == []
            expected_source_area = 3.0 if case == "non_xy_planar_closed_loop" else 0.5
            assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] == (
                expected_source_area
            )
            assert trace["closed_loop_planar_enclosed_area_m2"] == pytest.approx(
                expected_source_area * 0.0001
            )
            expected_compactness = (
                12 * pi / (5 + sqrt(13)) ** 2
                if case == "non_xy_planar_closed_loop"
                else 2 * pi / (2 + sqrt(2)) ** 2
            )
            assert trace["closed_loop_source_planar_isoperimetric_quotient"] == pytest.approx(
                expected_compactness
            )
            if case == "non_xy_planar_closed_loop":
                assert trace[
                    "closed_loop_planar_enclosed_area_scale_only_interval_m2"
                ] == pytest.approx([0.0, 0.0012])
            if case == "closed_loop_max_uncertainty":
                assert trace[
                    "closed_loop_planar_enclosed_area_scale_only_interval_m2"
                ] == pytest.approx([0.0, 0.0002])
        assert trace["nonadjacent_coincident_waypoint_index_pairs"] == []
        assert "closed_surface_trace_not_verified_anatomical_contour" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    else:
        assert trace["is_closed_surface_loop"] is False
        assert trace["closed_loop_source_exact_coplanarity"] is None
        assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == []
        assert trace["closed_loop_source_proper_crossing_segment_pairs"] is None
        assert trace["closed_loop_source_touching_segment_pairs"] is None
        assert trace["closed_loop_source_collinear_overlap_segment_pairs"] is None
        assert trace["closed_loop_source_is_simple_planar_perimeter"] is None
        assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == []
        assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] is None
        assert trace["closed_loop_planar_enclosed_area_m2"] is None
        assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None
        assert trace["turn_angles_deg"][0] is None
        assert trace["turn_angles_deg"][-1] is None
    if case == "ordinary":
        assert trace["nonadjacent_coincident_waypoint_index_pairs"] == []
        assert trace["reused_geometric_segment_source_length_mesh_units"] == 0.0
        assert trace["reused_geometric_segment_fraction_of_trace"] == 0.0
        assert trace["repeated_geometric_segment_index_pairs"] == []
        assert "surface_trace_reused_geometric_segment" not in trace["qc_warnings"]
        assert trace["geometric_detour_ratio"] == pytest.approx(1 + sqrt(2))
        assert trace["endpoint_chord_length_m"] == pytest.approx(0.01)
        assert trace["maximum_turn_angle_deg"] == pytest.approx(135.0)
        assert trace["total_absolute_geometric_turn_deg"] == pytest.approx(135.0)
    if case in ("uncertainty_missing", "segment_underflow"):
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
        assert trace["mesh_edge_face_incidence_counts"] == [2]
        assert trace["inconsistent_winding_segment_indices"] == [0]
        assert "inconsistent_winding_edge_on_surface_trace" in trace["qc_warnings"]
    if case == "duplicate_face":
        assert trace["mesh_edge_face_incidence_counts"] == [2]
        assert trace["duplicate_triangle_segment_indices"] == [0]
        assert "duplicate_triangle_on_surface_trace" in trace["qc_warnings"]
    if case == "geometric_seam":
        assert trace["split_vertex_nonmanifold_segment_indices"] == []
        assert trace["mesh_edge_face_incidence_counts"] == [1, 1]
        assert trace["geometric_edge_face_incidence_counts"] == [2, 1]
        assert trace["split_vertex_seam_segment_indices"] == [0]
        assert "split_vertex_geometric_seam_on_surface_trace" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "geometric_winding_seam":
        assert trace["mesh_edge_face_incidence_counts"] == [1, 1]
        assert trace["geometric_edge_face_incidence_counts"] == [2, 1]
        assert trace["split_vertex_winding_segment_indices"] == [0]
        assert trace["inconsistent_winding_segment_indices"] == []
        assert "split_vertex_hidden_winding_conflict_on_surface_trace" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "geometric_nonmanifold_seam":
        assert trace["mesh_edge_face_incidence_counts"] == [1]
        assert trace["geometric_edge_face_incidence_counts"] == [3]
        assert trace["split_vertex_seam_segment_indices"] == [0]
        assert trace["split_vertex_nonmanifold_segment_indices"] == [0]
        assert trace["nonmanifold_segment_indices"] == []
        assert "split_vertex_hidden_nonmanifold_on_surface_trace" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "nonmanifold":
        assert trace["split_vertex_nonmanifold_segment_indices"] == []
        assert trace["mesh_edge_face_incidence_counts"] == [3]
        assert trace["nonmanifold_segment_indices"] == [0]
        assert "nonmanifold_edge_on_surface_trace" in trace["qc_warnings"]
    if case == "segment_underflow":
        assert trace["source_segment_lengths_mesh_units"] == pytest.approx([1e-250], abs=0)
        assert trace["segment_lengths_m"] == [0.0]
        assert trace["length_scale_only_interval_m"] is None
        assert "calibrated_surface_trace_segment_underflow" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "finite_detour_chord_underflow":
        assert trace["source_endpoint_chord_mesh_units"] == pytest.approx(1e-250, rel=1e-12, abs=0)
        assert trace["source_trace_length_mesh_units"] == pytest.approx(2.0)
        assert trace["endpoint_chord_length_m"] == 0
        assert trace["endpoint_chord_scale_only_interval_m"] is None
        assert trace["geometric_detour_ratio"] == pytest.approx(2e250, rel=1e-12)
        assert "calibrated_surface_trace_endpoint_chord_underflow" in trace["qc_warnings"]
        assert "surface_trace_detour_ratio_unrepresentable" not in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "display_chord_rounding":
        assert trace["endpoint_chord_length_m"] > 0
        assert trace["geometric_detour_ratio"] > 1
        assert "surface_trace_endpoint_chord_display_coordinate_collapse" in (trace["qc_warnings"])
        assert trace["human_review_verified"] is False
    if case == "display_segment_rounding":
        assert trace["segment_lengths_m"][0] > 0
        assert trace["vertices_in_source_frame_m"][0] == trace["vertices_in_source_frame_m"][1]
        assert trace["display_coordinate_collapsed_segment_indices"] == [0]
        assert "surface_trace_segment_display_coordinate_collapse" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "reused_geometric_segment":
        assert trace["repeated_geometric_segment_index_pairs"] == [[0, 3]]
        assert trace["reused_geometric_segment_source_length_mesh_units"] == pytest.approx(1.0)
        assert trace["reused_geometric_segment_fraction_of_trace"] == pytest.approx(
            1.0 / (3 + sqrt(2))
        )
        assert "surface_trace_reused_geometric_segment" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "reverse_turn":
        assert trace["maximum_turn_angle_deg"] == pytest.approx(180.0)
        assert "surface_trace_180_degree_geometric_turn" in trace["qc_warnings"]
        assert trace["human_review_verified"] is False
    if case == "coincident_nonadjacent":
        assert trace["nonadjacent_coincident_waypoint_index_pairs"] == [[0, 2]]
        assert trace["geometric_detour_ratio"] is None
        assert "surface_trace_zero_endpoint_chord" in trace["qc_warnings"]
        assert (
            "nonadjacent_coincident_surface_trace_vertices"
            in artifact["surface_edge_traces"][0]["qc_warnings"]
        )
