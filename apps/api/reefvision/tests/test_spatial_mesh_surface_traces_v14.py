"""Caller-selected triangle-edge traces: provisional geometry and saved-workflow parity."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from itertools import combinations, pairwise
from math import dist, pi, sqrt
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


# A U-shaped, geometrically simple filled source contour has a centroid in
# its *empty notch*. This is not a biological attachment centroid.
CONCAVE_U_CLOSED_LOOP_PARAMS = {
    **PARAMS,
    "vertices": [
        [0, 0, 0],
        [4, 0, 0],
        [4, 4, 0],
        [3, 4, 0],
        [3, 1, 0],
        [1, 1, 0],
        [1, 4, 0],
        [0, 4, 0],
        [0, 1, 0],
        [4, 1, 0],
    ],
    "faces": [
        [0, 1, 9],
        [1, 2, 9],
        [9, 2, 3],
        [9, 3, 4],
        [0, 9, 4],
        [0, 4, 5],
        [0, 5, 8],
        [8, 5, 6],
        [8, 6, 7],
        [0, 8, 7],
    ],
    "surface_trace_vertex_paths": [[0, 1, 2, 3, 4, 5, 6, 7, 0]],
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

# This isolated thin triangle has a real source X span that is erased
# when its absolute coordinate extrema are independently calibrated. It must
# fail closed rather than publishing a false zero extent or renderer bounds.
COLLAPSED_BOUNDING_AXIS_PARAMS = {
    **PARAMS,
    "vertices": [[100.0, 0, 0], [100.00000000000001, 0, 0], [100.0, 2, 0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 1e-100,
    "surface_trace_vertex_paths": [[0, 1, 2]],
}

# The selected first edge still has a positive calibrated length and both
# displayed endpoints coincide. A connected second triangle widens the
# measured mesh X bounds so this valid preview does NOT silently weaken the
# calibrated bounding-span integrity check to exercise the trace warning.
DISPLAY_SEGMENT_ROUNDING_PARAMS = {
    **COLLAPSED_BOUNDING_AXIS_PARAMS,
    "vertices": [*COLLAPSED_BOUNDING_AXIS_PARAMS["vertices"], [99.0, 2, 0]],
    "faces": [[0, 1, 2], [0, 2, 3]],
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
    assert trace["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx(
        [1 / 3, 1 / 3, 0.0]
    )
    assert trace["closed_loop_planar_centroid_m"] == pytest.approx([0.01 / 3, 0.01 / 3, 0.0])
    assert trace["closed_loop_source_planar_centroid_inside_or_on_perimeter"] is True
    assert trace["closed_loop_planar_enclosed_area_scale_only_interval_m2"] == pytest.approx(
        [0.0000405, 0.0000605]
    )
    # Independent source-polygon reference for a right isosceles triangle.
    # Compactness is 4*pi*A/P^2, independent of calibration and path winding.
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] == pytest.approx(
        2 * pi / (2 + sqrt(2)) ** 2
    )
    # Equivalent-circle diameter is a scale-qualified geometric width, not
    # an anatomical branch diameter or a verified coral cross-section.
    source_diameter = sqrt(2 / pi)
    assert trace["closed_loop_source_planar_equivalent_diameter_mesh_units"] == pytest.approx(
        source_diameter
    )
    assert trace["closed_loop_planar_equivalent_diameter_m"] == pytest.approx(
        0.01 * source_diameter
    )
    assert trace["closed_loop_planar_equivalent_diameter_scale_only_interval_m"] == (
        pytest.approx([0.009 * source_diameter, 0.011 * source_diameter])
    )
    # A maximal vertex-pair chord is the geometric span of this triangle,
    # never an independently verified coral branch diameter or tissue width.
    assert trace["closed_loop_source_planar_maximum_vertex_chord_mesh_units"] == pytest.approx(
        sqrt(2)
    )
    assert trace["closed_loop_planar_maximum_vertex_chord_m"] == pytest.approx(0.01 * sqrt(2))
    assert trace["closed_loop_planar_maximum_vertex_chord_scale_only_interval_m"] == (
        pytest.approx([0.009 * sqrt(2), 0.011 * sqrt(2)])
    )
    offsets = trace["closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets"]
    assert offsets is not None
    assert sorted(path[offset] for offset in offsets) == [1, 2]
    assert trace["human_review_verified"] is False


def test_planar_footprint_non_xy_plane_and_full_scale_uncertainty() -> None:
    trace = measure_mesh_preview(**NON_XY_PLANAR_CLOSED_LOOP_PARAMS)["surface_edge_traces"][0]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] == pytest.approx(3.0)
    assert trace["closed_loop_planar_enclosed_area_m2"] == pytest.approx(0.0003)
    assert trace["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx(
        [0.0, 2 / 3, 1.0]
    )
    assert trace["closed_loop_planar_centroid_m"] == pytest.approx([0.0, 0.02 / 3, 0.01])
    assert trace["closed_loop_source_planar_centroid_inside_or_on_perimeter"] is True
    assert trace["closed_loop_planar_enclosed_area_scale_only_interval_m2"] == pytest.approx(
        [0.0, 0.0012]
    )
    # The non-XY triangle has area 3 and source perimeter 5 + sqrt(13).
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] == pytest.approx(
        12 * pi / (5 + sqrt(13)) ** 2
    )
    source_diameter = 2 * sqrt(3 / pi)
    assert trace["closed_loop_source_planar_equivalent_diameter_mesh_units"] == pytest.approx(
        source_diameter
    )
    assert trace["closed_loop_planar_equivalent_diameter_m"] == pytest.approx(
        0.01 * source_diameter
    )
    assert trace["closed_loop_planar_equivalent_diameter_scale_only_interval_m"] == (
        pytest.approx([0.0, 0.02 * source_diameter])
    )
    assert trace["closed_loop_source_planar_maximum_vertex_chord_mesh_units"] == pytest.approx(
        sqrt(13)
    )
    assert trace["closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets"] == [1, 2]
    assert trace["closed_loop_source_planar_chord_to_equivalent_diameter_ratio"] == pytest.approx(
        sqrt(13) / source_diameter
    )
    assert trace["closed_loop_planar_maximum_vertex_chord_m"] == pytest.approx(0.01 * sqrt(13))
    assert trace["closed_loop_planar_maximum_vertex_chord_scale_only_interval_m"] == (
        pytest.approx([0.0, 0.02 * sqrt(13)])
    )
    assert trace["human_review_verified"] is False


@pytest.mark.parametrize("scale", [0.01, 1.0])
@pytest.mark.parametrize(
    "path",
    [
        [0, 1, 2, 3, 4, 5, 6, 7, 0],
        [0, 7, 6, 5, 4, 3, 2, 1, 0],
        [4, 5, 6, 7, 0, 1, 2, 3, 4],
    ],
)
def test_concave_planar_centroid_can_be_outside_filled_perimeter(
    scale: float, path: list[int]
) -> None:
    params = {
        **CONCAVE_U_CLOSED_LOOP_PARAMS,
        "meters_per_unit": scale,
        "surface_trace_vertex_paths": [path],
    }
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    source_area = trace["closed_loop_source_planar_enclosed_area_mesh_units2"]
    assert source_area == pytest.approx(10.0)
    assert trace["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx([2.0, 1.7, 0.0])
    assert trace["closed_loop_planar_centroid_m"] == pytest.approx([2 * scale, 1.7 * scale, 0.0])
    assert trace["closed_loop_source_planar_centroid_inside_or_on_perimeter"] is False
    assert "closed_surface_trace_source_planar_centroid_outside_perimeter" in (trace["qc_warnings"])
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
    assert trace["closed_loop_planar_centroid_m"] is None
    assert trace["closed_loop_source_planar_centroid_mesh_units"] is None
    assert trace["closed_loop_source_planar_centroid_inside_or_on_perimeter"] is None
    assert trace["closed_loop_planar_enclosed_area_scale_only_interval_m2"] is None
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None
    assert trace["closed_loop_source_planar_equivalent_diameter_mesh_units"] is None
    assert trace["closed_loop_planar_equivalent_diameter_m"] is None
    assert trace["closed_loop_planar_equivalent_diameter_scale_only_interval_m"] is None
    assert trace["closed_loop_source_planar_maximum_vertex_chord_mesh_units"] is None
    assert trace["closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets"] is None
    assert trace["closed_loop_source_planar_chord_to_equivalent_diameter_ratio"] is None
    assert trace["closed_loop_planar_maximum_vertex_chord_m"] is None
    assert trace["closed_loop_planar_maximum_vertex_chord_scale_only_interval_m"] is None


@pytest.mark.parametrize("scale", [0.01, 1.0])
@pytest.mark.parametrize(
    "path",
    [[0, 1, 2, 0], [0, 2, 1, 0], [1, 2, 0, 1]],
)
def test_planar_elongation_ratio_is_scale_and_winding_invariant(
    scale: float, path: list[int]
) -> None:
    # Independent analytical reference for a right triangle (area 1/2,
    # maximum chord sqrt(2)); these are geometric, not anatomical measures.
    params = {
        **CLOSED_LOOP_PARAMS,
        "meters_per_unit": scale,
        "surface_trace_vertex_paths": [path],
    }
    trace = measure_mesh_preview(**params)["surface_edge_traces"][0]
    expected = sqrt(2) / (2 * sqrt(0.5 / pi))
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    assert trace["closed_loop_source_planar_chord_to_equivalent_diameter_ratio"] == (
        pytest.approx(expected)
    )
    assert trace["human_review_verified"] is False


def test_planar_maximum_vertex_chord_source_overflow_is_unknown_not_infinity() -> None:
    # Four finite edge lengths need not imply that an opposite-vertex chord
    # can be represented as binary64. Preserve null plus explicit geometric QC.
    points = [
        (1e308, 0.0, 0.0),
        (0.0, 1e308, 0.0),
        (-1e308, 0.0, 0.0),
        (0.0, -1e308, 0.0),
    ]
    trace = mesh_surface_edge_traces(
        points, [[0, 1, 2], [0, 2, 3]], [[0, 1, 2, 3, 0]], 1e-308, 0.1
    )[0]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    assert trace["closed_loop_source_planar_maximum_vertex_chord_mesh_units"] is None
    assert trace["closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets"] is None
    assert trace["closed_loop_source_planar_chord_to_equivalent_diameter_ratio"] is None
    assert trace["closed_loop_planar_maximum_vertex_chord_m"] is None
    assert trace["closed_loop_planar_maximum_vertex_chord_scale_only_interval_m"] is None
    assert (
        "closed_surface_trace_source_planar_maximum_chord_unrepresentable" in trace["qc_warnings"]
    )
    assert trace["human_review_verified"] is False


def test_planar_area_underflow_is_unknown_not_numeric_zero() -> None:
    vertices = [(0.0, 0.0, 0.0), (1e-200, 0.0, 0.0), (0.0, 1e-200, 0.0)]
    source = mesh_surface_edge_traces(vertices, [[0, 1, 2]], [[0, 1, 2, 0]], 1.0, 0.1)[0]
    assert source["closed_loop_source_is_simple_planar_perimeter"] is True
    assert source["closed_loop_source_planar_enclosed_area_mesh_units2"] is None
    # Positive linear coordinates remain measurable when their squared
    # source footprint is too small for a binary64 area.
    assert source["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx(
        [1e-200 / 3, 1e-200 / 3, 0.0], rel=1e-12, abs=0.0
    )
    assert source["closed_loop_planar_enclosed_area_m2"] is None
    assert source["closed_loop_source_planar_isoperimetric_quotient"] is None
    assert source["closed_loop_source_planar_equivalent_diameter_mesh_units"] is None
    assert source["closed_loop_planar_equivalent_diameter_m"] is None
    # Area underflow does not erase a positive, representable linear span.
    assert source["closed_loop_source_planar_maximum_vertex_chord_mesh_units"] == pytest.approx(
        sqrt(2) * 1e-200, rel=1e-12, abs=0.0
    )
    assert source["closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets"] == [1, 2]
    assert source["closed_loop_planar_maximum_vertex_chord_m"] == pytest.approx(
        sqrt(2) * 1e-200, rel=1e-12, abs=0.0
    )
    assert "closed_surface_trace_source_planar_area_unrepresentable" in source["qc_warnings"]

    ordinary = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    calibrated = mesh_surface_edge_traces(ordinary, [[0, 1, 2]], [[0, 1, 2, 0]], 1e-200, 0.1)[0]
    assert calibrated["closed_loop_source_planar_enclosed_area_mesh_units2"] == 0.5
    assert calibrated["closed_loop_planar_enclosed_area_m2"] is None
    assert calibrated["closed_loop_planar_enclosed_area_scale_only_interval_m2"] is None
    # A linear dimension can still be represented when its square cannot.
    source_diameter = sqrt(2 / pi)
    assert calibrated["closed_loop_planar_equivalent_diameter_m"] == pytest.approx(
        source_diameter * 1e-200, rel=1e-12, abs=0.0
    )
    assert calibrated["closed_loop_planar_equivalent_diameter_scale_only_interval_m"] == (
        pytest.approx(
            [source_diameter * 0.9e-200, source_diameter * 1.1e-200],
            rel=1e-12,
            abs=0.0,
        )
    )
    assert (
        "closed_surface_trace_calibrated_planar_area_unrepresentable" in calibrated["qc_warnings"]
    )


def test_planar_compactness_underflow_is_unknown_not_false_zero() -> None:
    # The area is representable but the area/perimeter² quotient is not.
    # Withholding a tiny positive value avoids a fabricated compactness of 0.
    points = [(0.0, 0.0, 0.0), (1e200, 0.0, 0.0), (0.0, 1e-200, 0.0)]
    trace = mesh_surface_edge_traces(points, [[0, 1, 2]], [[0, 1, 2, 0]], 1.0, None)[0]
    assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
    assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] == pytest.approx(0.5)
    assert trace["source_trace_length_mesh_units"] == pytest.approx(2e200)
    assert trace["closed_loop_source_planar_isoperimetric_quotient"] is None
    assert "closed_surface_trace_planar_compactness_unrepresentable" in trace["qc_warnings"]
    assert trace["human_review_verified"] is False


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


def test_collapsed_calibrated_mesh_bounds_fail_standalone_and_saved_graph(
    client: TestClient,
) -> None:
    # The same short edge is not independently valid as an isolated mesh:
    # calibrating its source X extrema erases its nonzero global X extent.
    params = COLLAPSED_BOUNDING_AXIS_PARAMS
    diagnostic = "Nonzero mesh axis span collapses after calibration"
    with pytest.raises(ValueError, match=diagnostic):
        measure_mesh_preview(**params)

    project_id = str(create_project(client, "Collapsed calibrated mesh bounds")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 400
    assert diagnostic in standalone.text

    graph = {
        "graph_id": "mesh-calibrated-bounds-collapse-v14",
        "name": "Reject false zero calibrated mesh bounds",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
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
        "concave_u_closed_loop",
        "concave_u_closed_loop_reverse",
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
        "cross_trace_unequal_overlap",
        "mixed_component_overlap",
        "oblique_component_overlap",
        "reused_geometric_segment",
        "display_chord_rounding",
        "display_segment_rounding",
        "uncertainty_missing",
        "uncertainty_max",
        "finite_detour_chord_underflow",
        "chain_chord_interval_underflow",
        "segment_underflow",
        "mixed_chain_underflow",
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
        "concave_u_closed_loop": CONCAVE_U_CLOSED_LOOP_PARAMS,
        "concave_u_closed_loop_reverse": {
            **CONCAVE_U_CLOSED_LOOP_PARAMS,
            "surface_trace_vertex_paths": [[0, 7, 6, 5, 4, 3, 2, 1, 0]],
        },
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
        "cross_trace_unequal_overlap": {
            **REVERSE_TURN_PARAMS,
            "surface_trace_vertex_paths": [[0, 1], [2, 1]],
        },
        "mixed_component_overlap": {
            **PARAMS,
            "vertices": [[i, 0, 0] for i in range(5)] + [[0, 1, 0]],
            "faces": [[0, 4, 5], [2, 4, 5], [1, 3, 5]],
            "surface_path_vertex_pairs": None,
            "surface_trace_vertex_paths": [[0, 4], [4, 2], [1, 3]],
        },
        "oblique_component_overlap": {
            **PARAMS,
            "vertices": [[i, 2 * i, 3 * i] for i in range(5)] + [[0, 1, 0]],
            "faces": [[0, 4, 5], [2, 4, 5], [1, 3, 5]],
            "surface_path_vertex_pairs": None,
            "surface_trace_vertex_paths": [[3, 1], [2, 4], [4, 0], [0, 4]],
        },
        "reused_geometric_segment": REUSED_GEOMETRIC_SEGMENT_PARAMS,
        "display_chord_rounding": DISPLAY_CHORD_ROUNDING_PARAMS,
        "display_segment_rounding": DISPLAY_SEGMENT_ROUNDING_PARAMS,
        "uncertainty_missing": {**PARAMS, "relative_scale_uncertainty": None},
        "uncertainty_max": {**PARAMS, "relative_scale_uncertainty": 1.0},
        "finite_detour_chord_underflow": FINITE_DETOUR_CHORD_UNDERFLOW_PARAMS,
        "chain_chord_interval_underflow": {
            **FINITE_DETOUR_CHORD_UNDERFLOW_PARAMS,
            "vertices": [[0, 0, 0], [1, 0, 0], [5e-224, 0, 0], [0, 1, 0]],
            "relative_scale_uncertainty": 0.9,
        },
        "segment_underflow": SEGMENT_UNDERFLOW_PREVIEW_PARAMS,
        "mixed_chain_underflow": {
            **SEGMENT_UNDERFLOW_PREVIEW_PARAMS,
            "surface_trace_vertex_paths": [[0, 1], [2, 3]],
        },
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
    record = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    artifact = record["payload_json"]
    if case in {
        "ordinary",
        "closed_loop",
        "finite_detour_chord_underflow",
        "chain_chord_interval_underflow",
        "cross_trace_unequal_overlap",
        "mixed_component_overlap",
        "oblique_component_overlap",
        "segment_underflow",
        "mixed_chain_underflow",
    }:
        replay = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert replay.status_code == 202, replay.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(replay.json()["job_id"])
        )
        replay_detail = client.get(f"/api/v1/workflow-runs/{replay.json()['id']}")
        assert replay_detail.status_code == 200, replay_detail.text
        assert replay_detail.json()["run"]["status"] == "succeeded"
        replay_record = next(
            item
            for item in replay_detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        )
        assert replay_record["payload_json"] == artifact
        assert replay_record["payload_sha256"] == record["payload_sha256"]
    assert artifact["surface_edge_traces"] == standalone.json()["surface_edge_traces"]
    union = artifact["surface_trace_exact_edge_union"]
    assert union == standalone.json()["surface_trace_exact_edge_union"]
    overlaps = case in {
        "mixed_component_overlap",
        "oblique_component_overlap",
        "contact_overlap_closed_loop",
        "reverse_turn",
        "cross_trace_unequal_overlap",
        "display_chord_rounding",
        "finite_detour_chord_underflow",
        "chain_chord_interval_underflow",
    }
    mixed_overlap = case in {"mixed_component_overlap", "oblique_component_overlap"}
    assert union["unequal_collinear_overlap_pair_count"] == (3 if mixed_overlap else int(overlaps))
    if mixed_overlap:
        assert union["cross_component_unequal_collinear_overlap_pair_count"] == 2
        assert [
            item["unequal_collinear_overlap_pair_count"]
            for item in union["endpoint_graph_components"]
        ] == [1, 0]
        local = [
            item["collinear_overlap_corrected_union"] for item in union["endpoint_graph_components"]
        ]
        factor = sqrt(14) if case == "oblique_component_overlap" else 1.0
        assert [item["source_length_mesh_units"] for item in local] == pytest.approx(
            [4 * factor, 2 * factor]
        )
        assert [item["length_m"] for item in local] == pytest.approx([0.04 * factor, 0.02 * factor])
        assert local[0]["length_scale_only_interval_m"] == pytest.approx(
            [0.036 * factor, 0.044 * factor]
        )
        assert local[1]["length_scale_only_interval_m"] == pytest.approx(
            [0.018 * factor, 0.022 * factor]
        )
        # Overlap between components is corrected only in the global union.
        assert union["collinear_overlap_corrected_union"]["length_m"] == pytest.approx(
            0.04 * factor
        )
        assert union["nonzero_edge_traversal_count"] == (
            4 if case == "oblique_component_overlap" else 3
        )
        assert union["distinct_nonzero_edge_count"] == 3
    overlap_warning = "surface_trace_unequal_collinear_edges_overlap"
    assert (overlap_warning in union["qc_warnings"]) is overlaps
    assert (overlap_warning in artifact["qc_warnings"]) is overlaps
    cross_warning = "surface_trace_cross_component_collinear_overlap"
    cross_overlap = union["cross_component_unequal_collinear_overlap_pair_count"] > 0
    assert (cross_warning in union["qc_warnings"]) is cross_overlap
    assert artifact["qc_warnings"].count(cross_warning) == int(cross_overlap)
    corrected = union["collinear_overlap_corrected_union"]
    assert artifact["qc_warnings"] == standalone.json()["qc_warnings"]
    assert set(union["qc_warnings"]) <= set(artifact["qc_warnings"])
    assert set(corrected["qc_warnings"]) <= set(artifact["qc_warnings"])
    assert corrected["human_review_verified"] is False
    assert corrected["biological_validation_status"] == "not_verified_anatomical_centerline"
    if not overlaps:
        assert corrected["source_length_mesh_units"] == union["source_length_mesh_units"]
        assert corrected["length_m"] == union["length_m"]
        assert corrected["length_scale_only_interval_m"] == union["length_scale_only_interval_m"]
    if case == "cross_trace_unequal_overlap":
        assert union["source_length_mesh_units"] == pytest.approx(3.0)
        assert union["length_m"] == pytest.approx(0.03)
        assert union["length_scale_only_interval_m"] == pytest.approx([0.027, 0.033])
        assert corrected["source_length_mesh_units"] == pytest.approx(2.0)
        assert corrected["length_m"] == pytest.approx(0.02)
        assert corrected["length_scale_only_interval_m"] == pytest.approx([0.018, 0.022])
        assert corrected["qc_warnings"] == []
        assert artifact["surface_trace_shared_geometric_edge_pairs"] == []
    topology = union["endpoint_graph_topology"]
    assert topology["human_review_verified"] is False
    assert topology["biological_validation_status"] == "not_verified_anatomical_centerline"
    chains = union["endpoint_graph_chains"]
    _assert_chain_traversals(chains, params["vertices"], params["surface_trace_vertex_paths"])
    _assert_endpoint_components(
        union,
        params["vertices"],
        params["surface_trace_vertex_paths"],
        params["meters_per_unit"],
        params["relative_scale_uncertainty"],
    )
    assert sum(chain["edge_count"] for chain in chains) == union["distinct_nonzero_edge_count"]
    assert all(chain["human_review_verified"] is False for chain in chains)
    if case in {"ordinary", "closed_loop", "segment_underflow"}:
        assert len(chains) == 1
        midpoint = chains[0]["source_arc_midpoint_mesh_units"]
        if case == "ordinary":
            fraction = (sqrt(2) - 1) / (2 * sqrt(2))
            assert midpoint == pytest.approx([fraction, 1 - fraction, 0.0])
            assert chains[0]["source_arc_midpoint_chain_edge_offset"] == 1
        elif case == "closed_loop":
            assert midpoint == pytest.approx([0.5, 0.5, 0.0])
            assert chains[0]["source_arc_midpoint_chain_edge_offset"] == 1
        else:
            assert midpoint == pytest.approx([5e-251, 0.0, 0.0], abs=0)
            assert chains[0]["source_arc_midpoint_chain_edge_offset"] == 0
    for chain in chains:
        # Compute from source waypoints and round each final bound only once.
        # A rounded nominal meter chord is not an exact uncertainty oracle.
        waypoints = chain["source_waypoints_mesh_units"]
        lengths = [Fraction(dist(a, b)) for a, b in pairwise(waypoints)]
        offset = chain["source_arc_midpoint_chain_edge_offset"]
        locator = chain["source_arc_midpoint_edge_fraction"]
        edge_fraction = Fraction(int(locator["numerator"]), int(locator["denominator"]))
        assert 0 < edge_fraction <= 1
        assert locator == {
            "numerator": str(edge_fraction.numerator),
            "denominator": str(edge_fraction.denominator),
        }
        assert (
            sum(lengths[:offset], Fraction(0)) + edge_fraction * lengths[offset]
            == sum(lengths, Fraction(0)) / 2
        )
        total = sum(lengths, Fraction(0))
        weights = [length / total for length in lengths]
        expected_offset = max(range(len(weights)), key=weights.__getitem__)
        assert chain["source_longest_edge_chain_offset"] == expected_offset
        assert chain["source_longest_edge_arc_fraction"] == float(weights[expected_offset])
        expected_centroid = []
        for coordinates in zip(*waypoints, strict=True):
            midpoints = [(Fraction(a) + Fraction(b)) / 2 for a, b in pairwise(coordinates)]
            weighted = sum(w * m for w, m in zip(weights, midpoints, strict=True))
            expected_centroid.append(float(weighted))
        assert chain["source_arc_centroid_mesh_units"] == expected_centroid
        assert chain["source_arc_midpoint_mesh_units"] == [
            float((1 - edge_fraction) * Fraction(a) + edge_fraction * Fraction(b))
            for a, b in zip(waypoints[offset], waypoints[offset + 1], strict=True)
        ]
        chord = Fraction(dist(waypoints[0], waypoints[-1]))
        calibrated_chord = chord * Fraction(params["meters_per_unit"])
        nominal_chord = float(calibrated_chord)
        if chord > 0 and nominal_chord == 0:
            assert chain["endpoint_chord_length_m"] is None
            assert chain["endpoint_chord_length_scale_only_interval_m"] is None
            assert "surface_trace_chain_chord_underflow" in chain["qc_warnings"]
        else:
            assert chain["endpoint_chord_length_m"] == nominal_chord
            uncertainty = params["relative_scale_uncertainty"]
            if uncertainty is None:
                assert chain["endpoint_chord_length_scale_only_interval_m"] is None
            else:
                relative = Fraction(uncertainty)
                lower = float(calibrated_chord * (1 - relative))
                upper = float(calibrated_chord * (1 + relative))
                if chord > 0 and (
                    (relative < 1 and lower == 0) or (relative > 0 and lower == upper)
                ):
                    assert chain["endpoint_chord_length_scale_only_interval_m"] is None
                    warning = "surface_trace_chain_chord_interval_unrepresentable"
                    assert warning in chain["qc_warnings"]
                else:
                    assert chain["endpoint_chord_length_scale_only_interval_m"] == [lower, upper]
    assert {warning for chain in chains for warning in chain["qc_warnings"]} <= set(
        artifact["qc_warnings"]
    )
    if case == "chain_chord_interval_underflow":
        # A positive subnormal nominal chord survives, but the nonzero
        # lower bound rounds to zero. This is not a true zero chord.
        assert len(chains) == 1
        assert chains[0]["endpoint_chord_length_m"] == 5e-324
        assert chains[0]["endpoint_chord_length_scale_only_interval_m"] is None
        warning = "surface_trace_chain_chord_interval_unrepresentable"
        assert warning in chains[0]["qc_warnings"]
        assert warning in artifact["qc_warnings"]
        assert "surface_trace_chain_chord_underflow" not in chains[0]["qc_warnings"]
    if case == "mixed_chain_underflow":
        warning = "surface_trace_chain_length_underflow"
        assert union["qc_warnings"] == corrected["qc_warnings"] == []
        assert union["length_m"] == pytest.approx(sqrt(2) * 1e-100, abs=0)
        assert corrected["length_m"] == union["length_m"]
        assert len(chains) == 2
        assert chains[0]["source_length_mesh_units"] == pytest.approx(1e-250, abs=0)
        assert chains[0]["length_m"] is None
        assert chains[0]["length_scale_only_interval_m"] is None
        assert chains[0]["qc_warnings"] == [warning, "surface_trace_chain_chord_underflow"]
        assert chains[1]["length_m"] == union["length_m"]
        assert chains[1]["qc_warnings"] == []
        assert chains[0]["selected_trace_memberships"] == [
            {"trace_index": 0, "chain_edge_offsets": [0]}
        ]
        assert chains[1]["selected_trace_memberships"] == [
            {"trace_index": 1, "chain_edge_offsets": [0]}
        ]
        assert artifact["qc_warnings"].count(warning) == 1
        components = union["endpoint_graph_components"]
        component_warning = "surface_trace_component_length_underflow"
        assert components[0]["length_m"] is None
        span_warning = "surface_trace_component_axis_span_underflow"
        assert components[0]["qc_warnings"] == [component_warning, span_warning]
        local_corrected = components[0]["collinear_overlap_corrected_union"]
        assert local_corrected["length_m"] is None
        assert local_corrected["length_scale_only_interval_m"] is None
        local_warning = "surface_trace_collinear_union_length_underflow"
        assert local_corrected["qc_warnings"] == [local_warning]
        assert local_warning in artifact["qc_warnings"]
        assert None in components[0]["axis_aligned_spans_m"]
        assert artifact["qc_warnings"].count(span_warning) == 1
        assert components[1]["length_m"] == union["length_m"]
        assert artifact["qc_warnings"].count(component_warning) == 1
    if case in {"closed_loop", "closed_loop_reverse", "closed_loop_rotated"}:
        assert union["endpoint_graph_components"][0]["source_endpoint_graph_landmarks"] == []
        assert len(chains) == 1
        assert chains[0]["is_closed"] is True
        assert chains[0]["selected_trace_memberships"] == [
            {"trace_index": 0, "chain_edge_offsets": [0, 1, 2]}
        ]
        assert chains[0]["source_waypoints_mesh_units"] == [
            [0, 0, 0],
            [0, 1, 0],
            [1, 0, 0],
            [0, 0, 0],
        ]
        assert chains[0]["source_length_mesh_units"] == pytest.approx(2 + sqrt(2))
        assert chains[0]["endpoint_graph_degrees"] == [2, 2]
        assert chains[0]["source_chain_geometry_sha256"] == (
            "f371682a882db4038a7bb7b121baeb4dcf9f5126a2979177352894a8ed089cdb"
        )
        assert topology["vertex_count"] == 3
        assert topology["connected_component_count"] == 1
        assert topology["degree_one_vertex_count"] == 0
        assert topology["degree_three_or_more_vertex_count"] == 0
        assert topology["cycle_rank"] == 1
    if case == "ordinary":
        assert len(chains) == 1
        assert chains[0]["is_closed"] is False
        assert chains[0]["source_waypoints_mesh_units"] == [
            [0, 0, 0],
            [0, 1, 0],
            [1, 0, 0],
        ]
        assert chains[0]["length_m"] == pytest.approx(0.01 * (1 + sqrt(2)))
        assert chains[0]["endpoint_graph_degrees"] == [1, 1]
        assert chains[0]["source_chain_geometry_sha256"] == (
            "dd2f72285179362d3e0783cc74f3dabca119d597806abced40b93260edda4ac9"
        )
        assert topology["vertex_count"] == 3
        assert topology["connected_component_count"] == 1
        assert topology["degree_one_vertex_count"] == 2
        assert topology["degree_three_or_more_vertex_count"] == 0
        assert topology["cycle_rank"] == 0
    assert union["human_review_verified"] is False
    if case == "segment_underflow":
        assert union["source_length_mesh_units"] == pytest.approx(1e-250, abs=0)
        assert union["length_m"] is None
        assert union["length_scale_only_interval_m"] is None
        assert union["qc_warnings"] == ["surface_trace_exact_edge_union_length_underflow"]
        assert corrected["qc_warnings"] == ["surface_trace_collinear_union_length_underflow"]
        assert chains[0]["length_m"] is None
        assert chains[0]["length_scale_only_interval_m"] is None
        assert chains[0]["qc_warnings"] == [
            "surface_trace_chain_length_underflow",
            "surface_trace_chain_chord_underflow",
        ]
    if case == "reused_geometric_segment":
        assert union["nonzero_edge_traversal_count"] == 4
        assert union["distinct_nonzero_edge_count"] == 3
        assert union["within_trace_redundant_traversal_count"] == 1
        assert union["cross_trace_redundant_traversal_count"] == 0
        assert union["redundant_traversal_source_length_mesh_units"] == pytest.approx(1.0)
        assert union["within_trace_redundant_source_length_mesh_units"] == 1.0
        assert union["cross_trace_redundant_source_length_mesh_units"] == 0.0
        assert union["cross_trace_shared_source_length_mesh_units"] == 0.0
        assert union["cross_trace_shared_source_length_fraction"] == 0.0
    if case == "uncertainty_missing":
        assert union["length_scale_only_interval_m"] is None
        assert union["qc_warnings"] == []
    if case == "uncertainty_max":
        assert union["length_scale_only_interval_m"] == pytest.approx([0.0, 2 * union["length_m"]])
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
    assert "closed_loop_source_planar_centroid_mesh_units" in trace
    assert "closed_loop_source_planar_centroid_inside_or_on_perimeter" in trace
    inside = trace["closed_loop_source_planar_centroid_inside_or_on_perimeter"]
    assert "closed_loop_planar_centroid_m" in trace
    if case in (
        "closed_loop",
        "closed_loop_reverse",
        "closed_loop_rotated",
        "closed_loop_max_uncertainty",
    ):
        assert trace["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx(
            [1 / 3, 1 / 3, 0.0]
        )
        assert inside is True
    elif case == "non_xy_planar_closed_loop":
        assert trace["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx(
            [0.0, 2 / 3, 1.0]
        )
        assert inside is True
    elif case.startswith("concave_u"):
        assert trace["closed_loop_source_planar_centroid_mesh_units"] == pytest.approx(
            [2.0, 1.7, 0.0]
        )
        assert inside is False
    else:
        assert trace["closed_loop_source_planar_centroid_mesh_units"] is None
        assert inside is None
    assert "closed_loop_source_planar_maximum_vertex_chord_mesh_units" in trace
    assert "closed_loop_source_planar_maximum_vertex_chord_waypoint_offsets" in trace
    assert "closed_loop_planar_maximum_vertex_chord_m" in trace
    assert "closed_loop_planar_maximum_vertex_chord_scale_only_interval_m" in trace
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
        "concave_u_closed_loop",
        "concave_u_closed_loop_reverse",
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
                expected_absolute_turn = 720.0 if case.startswith("concave_u") else 360.0
                assert trace["total_absolute_geometric_turn_deg"] == pytest.approx(
                    expected_absolute_turn
                )
            assert trace["closed_loop_source_exact_coplanarity"] is True
            assert trace["closed_loop_source_noncoplanar_waypoint_offsets"] == []
            assert trace["closed_loop_source_proper_crossing_segment_pairs"] == []
            assert trace["closed_loop_source_touching_segment_pairs"] == []
            assert trace["closed_loop_source_collinear_overlap_segment_pairs"] == []
            assert trace["closed_loop_source_is_simple_planar_perimeter"] is True
            assert trace["closed_loop_source_local_backtrack_waypoint_offsets"] == []
            expected_source_area = (
                10.0
                if case.startswith("concave_u")
                else 3.0
                if case == "non_xy_planar_closed_loop"
                else 0.5
            )
            assert trace["closed_loop_source_planar_enclosed_area_mesh_units2"] == (
                expected_source_area
            )
            assert trace["closed_loop_planar_enclosed_area_m2"] == pytest.approx(
                expected_source_area * 0.0001
            )
            # This value is present in both standalone and the persisted typed
            # graph artifact, whose full payload/provenance equality is checked.
            diameter = 2 * sqrt(expected_source_area / pi)
            assert trace["closed_loop_source_planar_equivalent_diameter_mesh_units"] == (
                pytest.approx(diameter)
            )
            assert trace["closed_loop_planar_equivalent_diameter_m"] == pytest.approx(
                0.01 * diameter
            )
            expected_compactness = (
                10 * pi / 121
                if case.startswith("concave_u")
                else 12 * pi / (5 + sqrt(13)) ** 2
                if case == "non_xy_planar_closed_loop"
                else 2 * pi / (2 + sqrt(2)) ** 2
            )
            assert trace["closed_loop_source_planar_isoperimetric_quotient"] == pytest.approx(
                expected_compactness
            )
            source_maximum_span = (
                4 * sqrt(2)
                if case.startswith("concave_u")
                else sqrt(13)
                if case == "non_xy_planar_closed_loop"
                else sqrt(2)
            )
            assert trace["closed_loop_source_planar_maximum_vertex_chord_mesh_units"] == (
                pytest.approx(source_maximum_span)
            )
            assert trace["closed_loop_planar_maximum_vertex_chord_m"] == pytest.approx(
                0.01 * source_maximum_span
            )
            assert trace["closed_loop_source_planar_chord_to_equivalent_diameter_ratio"] == (
                pytest.approx(source_maximum_span / diameter)
            )
            assert trace["closed_loop_planar_maximum_vertex_chord_scale_only_interval_m"] == (
                pytest.approx(
                    [
                        0.0
                        if case in ("non_xy_planar_closed_loop", "closed_loop_max_uncertainty")
                        else 0.009 * source_maximum_span,
                        0.02 * source_maximum_span
                        if case in ("non_xy_planar_closed_loop", "closed_loop_max_uncertainty")
                        else 0.011 * source_maximum_span,
                    ]
                )
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
    if case in ("uncertainty_missing", "segment_underflow", "mixed_chain_underflow"):
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


def _overlap_pair_count(edges: list[frozenset[tuple[float, ...]]]) -> int:
    # Independent pairwise exact-coordinate oracle: project onto one nonzero
    # axis and test both endpoints against the first segment's infinite line.
    count = 0
    for first, second in combinations(edges, 2):
        a, b = [tuple(map(Fraction, point)) for point in sorted(first)]
        c, d = [tuple(map(Fraction, point)) for point in sorted(second)]
        axis = next(i for i in range(3) if a[i] != b[i])
        if all(
            (point[i] - a[i]) * (b[axis] - a[axis]) == (point[axis] - a[axis]) * (b[i] - a[i])
            for point in (c, d)
            for i in range(3)
        ) and max(a[axis], c[axis]) < min(b[axis], d[axis]):
            count += 1
    return count


def _assert_endpoint_components(
    union: dict[str, Any],
    vertices: list[list[float]],
    paths: list[list[int]],
    scale: float = 0.01,
    uncertainty: float | None = 0.1,
) -> None:
    # Independent set-merging oracle, starting from submitted edges.
    edges = {
        frozenset((tuple(vertices[a]), tuple(vertices[b])))
        for path in paths
        for a, b in pairwise(path)
        if vertices[a] != vertices[b]
    }
    groups: list[set[tuple[float, ...]]] = []
    for edge in edges:
        joined = set(edge)
        separate = []
        for group in groups:
            if joined.intersection(group):
                joined.update(group)
            else:
                separate.append(group)
        groups = [*separate, joined]
    expected: list[dict[str, Any]] = []
    chains = union["endpoint_graph_chains"]
    for group in sorted(groups, key=min):
        group_edges = [edge for edge in edges if edge <= group]
        degrees = [sum(point in edge for edge in group_edges) for point in group]
        source_length = sum((Fraction(dist(*edge)) for edge in group_edges), Fraction(0))
        calibrated = source_length * Fraction(scale)
        nominal = float(calibrated)
        interval = None
        warnings = []
        if nominal == 0:
            warnings.append("surface_trace_component_length_underflow")
        elif uncertainty is not None:
            lower = float(calibrated * (1 - Fraction(uncertainty)))
            upper = float(calibrated * (1 + Fraction(uncertainty)))
            if (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper):
                warnings.append("surface_trace_component_interval_unrepresentable")
            else:
                interval = [lower, upper]
        canonical_edges = [
            [[float(value) if value else 0.0 for value in point] for point in edge]
            for edge in sorted(tuple(sorted(edge)) for edge in group_edges)
        ]
        digest = hashlib.sha256(
            json.dumps(canonical_edges, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        minima = [min(point[axis] for point in group) for axis in range(3)]
        maxima = [max(point[axis] for point in group) for axis in range(3)]
        exact_spans = [
            (Fraction(high) - Fraction(low)) * Fraction(scale)
            for low, high in zip(minima, maxima, strict=True)
        ]
        spans = [None if span and not float(span) else float(span) for span in exact_spans]
        intervals: list[list[float] | None] = []
        lost_interval = False
        for span, nominal_span in zip(exact_spans, spans, strict=True):
            if nominal_span is None or uncertainty is None:
                intervals.append(None)
                continue
            error = span * Fraction(uncertainty)
            limits = [float(span - error), float(span + error)]
            if span and ((uncertainty < 1 and not limits[0]) or (error and limits[0] == limits[1])):
                lost_interval = True
                intervals.append(None)
            else:
                intervals.append(limits)
        if None in spans:
            warnings.append("surface_trace_component_axis_span_underflow")
        if lost_interval:
            warnings.append("surface_trace_component_axis_span_interval_unrepresentable")
        # Independently enumerate the original submitted steps in this component.
        selected_steps = [
            (trace_index, frozenset((tuple(vertices[a]), tuple(vertices[b]))))
            for trace_index, path in enumerate(paths)
            for a, b in pairwise(path)
            if vertices[a] != vertices[b]
            and tuple(vertices[a]) in group
            and tuple(vertices[b]) in group
        ]
        expected.append(
            {
                "selected_trace_indices": sorted({index for index, _ in selected_steps}),
                "nonzero_edge_traversal_count": len(selected_steps),
                "distinct_trace_edge_membership_count": len(set(selected_steps)),
                "source_min_vertex_mesh_units": list(min(group)),
                "source_axis_aligned_bounds_mesh_units": {"minimum": minima, "maximum": maxima},
                "axis_aligned_spans_m": spans,
                "axis_aligned_span_scale_only_intervals_m": intervals,
                "source_component_geometry_sha256": digest,
                "source_component_geometry_canonicalization": "sorted_float64_xyz_edges_json_v1",
                "vertex_count": len(group),
                "distinct_nonzero_edge_count": len(group_edges),
                "degree_one_vertex_count": degrees.count(1),
                "degree_three_or_more_vertex_count": sum(degree >= 3 for degree in degrees),
                "cycle_rank": len(group_edges) - len(group) + 1,
                "unequal_collinear_overlap_pair_count": _overlap_pair_count(group_edges),
                "source_endpoint_graph_landmarks": [
                    {"source_vertex_mesh_units": list(point), "degree": degree}
                    for point in sorted(group)
                    if (degree := sum(point in edge for edge in group_edges)) != 2
                ],
                "source_length_mesh_units": float(source_length),
                "length_m": nominal if nominal > 0 else None,
                "length_scale_only_interval_m": interval,
                "qc_warnings": warnings,
                "chain_indices": [
                    index
                    for index, chain in enumerate(chains)
                    if all(tuple(point) in group for point in chain["source_waypoints_mesh_units"])
                ],
                "biological_validation_status": "not_verified_anatomical_centerline",
                "human_review_verified": False,
            }
        )
    actual = union["endpoint_graph_components"]
    for component, reference in zip(actual, expected, strict=True):
        corrected = component["collinear_overlap_corrected_union"]
        assert corrected["human_review_verified"] is False
        assert corrected["biological_validation_status"] == "not_verified_anatomical_centerline"
        assert corrected["method"] == "exact_source_line_positive_overlap_union"
        if not reference["unequal_collinear_overlap_pair_count"]:
            assert corrected["source_length_mesh_units"] == reference["source_length_mesh_units"]
            assert corrected["length_m"] == reference["length_m"]
            assert (
                corrected["length_scale_only_interval_m"]
                == reference["length_scale_only_interval_m"]
            )
    corrected_key = "collinear_overlap_corrected_union"
    assert [
        {key: value for key, value in component.items() if key != corrected_key}
        for component in actual
    ] == expected
    assert union["unequal_collinear_overlap_pair_count"] == _overlap_pair_count(list(edges))
    assert union["cross_component_unequal_collinear_overlap_pair_count"] == (
        _overlap_pair_count(list(edges))
        - sum(item["unequal_collinear_overlap_pair_count"] for item in expected)
    )
    assert (
        sum(item["nonzero_edge_traversal_count"] for item in expected)
        == union["nonzero_edge_traversal_count"]
    )
    assert sum(item["distinct_trace_edge_membership_count"] for item in expected) == (
        union["distinct_nonzero_edge_count"] + union["cross_trace_redundant_traversal_count"]
    )
    assert sorted(index for item in expected for index in item["chain_indices"]) == list(
        range(len(chains))
    )


def _assert_chain_traversals(
    chains: list[dict[str, Any]], vertices: list[list[float]], paths: list[list[int]]
) -> None:
    # Independent directed scan, without the service's reverse edge index.
    for chain in chains:
        chain_pairs = list(pairwise(chain["source_waypoints_mesh_units"]))
        # Independent geometric oracle, also exercised by saved-graph parity.
        chord = dist(chain_pairs[0][0], chain_pairs[-1][1])
        assert chain["source_endpoint_chord_mesh_units"] == pytest.approx(chord, abs=0)
        length = sum(dist(first, last) for first, last in chain_pairs)
        if chain["is_closed"]:
            assert chain["endpoint_straightness_ratio"] is None
        else:
            assert chain["endpoint_straightness_ratio"] == pytest.approx(chord / length)
        expected = []
        for trace_index, path in enumerate(paths):
            for trace_offset, (a, b) in enumerate(pairwise(path)):
                for chain_offset, (first, last) in enumerate(chain_pairs):
                    forward = vertices[a] == first and vertices[b] == last
                    reverse = vertices[b] == first and vertices[a] == last
                    if forward or reverse:
                        expected.append(
                            {
                                "trace_index": trace_index,
                                "trace_edge_offset": trace_offset,
                                "chain_edge_offset": chain_offset,
                                "follows_chain_orientation": forward,
                            }
                        )
        assert chain["selected_trace_traversals"] == expected
        # Compare each canonical edge independently against the original
        # directed selections, including repeated traversals in one trace.
        source_lengths_by_support: dict[int, list[Fraction]] = {}
        for offset, (first, last) in enumerate(chain_pairs):
            forward_count = 0
            reverse_count = 0
            trace_count = 0
            for path in paths:
                forward = sum(
                    vertices[a] == first and vertices[b] == last for a, b in pairwise(path)
                )
                reverse = sum(
                    vertices[a] == last and vertices[b] == first for a, b in pairwise(path)
                )
                forward_count += forward
                reverse_count += reverse
                trace_count += int(forward + reverse > 0)
            assert chain["selected_chain_edge_support"][offset] == {
                "chain_edge_offset": offset,
                "distinct_trace_count": trace_count,
                "forward_traversal_count": forward_count,
                "reverse_traversal_count": reverse_count,
            }
            source_lengths_by_support.setdefault(trace_count, []).append(
                Fraction(dist(first, last))
            )
        assert len(chain["selected_chain_edge_support"]) == len(chain_pairs)
        assert chain["source_arc_length_by_distinct_trace_count"] == [
            {
                "distinct_trace_count": count,
                "edge_count": len(lengths),
                "source_length_mesh_units": float(sum(lengths, Fraction(0))),
            }
            for count, lengths in sorted(source_lengths_by_support.items())
        ]
    assert sum(len(chain["selected_trace_traversals"]) for chain in chains) == sum(
        vertices[a] != vertices[b] for path in paths for a, b in pairwise(path)
    )


@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize("split_indices", [False, True])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_cross_trace_shared_edges_are_not_independent_branch_lengths(
    client: TestClient, shared: bool, split_indices: bool, reverse_order: bool
) -> None:
    # Two tip routes on a Y-shaped reference share a two-unit trunk.
    # Reverse the second route and optionally use separate seam indices.
    vertices = [[0, 0, 0], [2, 0, 0], [2, 3, 0], [2, 0, 4]]
    faces = [[0, 1, 2], [1, 0, 3]]
    root, junction = 0, 1
    if split_indices:
        vertices.extend([[0, 0, 0], [2, 0, 0]])
        root, junction = 4, 5
        faces[1] = [junction, root, 3]
    # An intervening edge touches both routes at most at endpoints; shared
    # trunk detection must compare nonadjacent selections in either order.
    paths = [[0, 1, 2], [2, 0], [3, junction, root] if shared else [3, junction]]
    expected_lengths = [0.05, sqrt(13) * 0.01, 0.06 if shared else 0.04]
    if reverse_order:
        paths.reverse()
        expected_lengths.reverse()
    params = {
        **PARAMS,
        "vertices": vertices,
        "faces": faces,
        "surface_path_vertex_pairs": None,
        "surface_trace_vertex_paths": paths,
    }
    direct = measure_mesh_preview(**params)
    warning = "surface_traces_share_geometric_edges"
    assert (warning in direct["qc_warnings"]) is shared
    expected_pairs = (
        [{"trace_indices": [0, 2], "shared_distinct_geometric_edge_count": 1}] if shared else []
    )
    assert direct["surface_trace_shared_geometric_edge_pairs"] == expected_pairs
    union = direct["surface_trace_exact_edge_union"]
    source_length = 9 + sqrt(13)
    assert union["distinct_nonzero_edge_count"] == 4
    assert union["unequal_collinear_overlap_pair_count"] == 0
    chains = union["endpoint_graph_chains"]
    _assert_chain_traversals(chains, vertices, paths)
    _assert_endpoint_components(union, vertices, paths)
    assert [chain["edge_count"] for chain in chains] == [3, 1]
    support = chains[0]["source_arc_length_by_distinct_trace_count"]
    assert len(support) == (2 if shared else 1)
    assert support[0]["distinct_trace_count"] == 1
    assert support[0]["edge_count"] == (2 if shared else 3)
    assert support[0]["source_length_mesh_units"] == pytest.approx(
        3 + sqrt(13) if shared else 5 + sqrt(13)
    )
    if shared:
        assert support[1] == {
            "distinct_trace_count": 2,
            "edge_count": 1,
            "source_length_mesh_units": 2.0,
        }
    first_trace, last_trace = (2, 0) if reverse_order else (0, 2)
    loop_memberships = [
        {"trace_index": first_trace, "chain_edge_offsets": [0, 2]},
        {"trace_index": 1, "chain_edge_offsets": [1]},
    ]
    if shared:
        loop_memberships.append({"trace_index": last_trace, "chain_edge_offsets": [0]})
    assert chains[0]["selected_trace_memberships"] == sorted(
        loop_memberships, key=lambda item: item["trace_index"]
    )
    assert chains[1]["selected_trace_memberships"] == [
        {"trace_index": last_trace, "chain_edge_offsets": [0]}
    ]
    assert [chain["is_closed"] for chain in chains] == [True, False]
    assert [chain["endpoint_graph_degrees"] for chain in chains] == [[3, 3], [3, 1]]
    assert union["endpoint_graph_components"][0]["source_endpoint_graph_landmarks"] == [
        {"source_vertex_mesh_units": [2, 0, 0], "degree": 3},
        {"source_vertex_mesh_units": [2, 0, 4], "degree": 1},
    ]
    assert [chain["source_chain_geometry_sha256"] for chain in chains] == [
        "68f72cd19b70a9ad34a3f467194d6819d00d427a1fac1616ffe93f987af30469",
        "445e311472282eff7992e2124f223b752110241a2d68897ec0bd7a9d9726b1d0",
    ]
    assert all(
        chain["source_chain_geometry_canonicalization"] == "ordered_float64_xyz_compact_json_v1"
        for chain in chains
    )
    assert [chain["source_waypoints_mesh_units"] for chain in chains] == [
        [[2, 0, 0], [0, 0, 0], [2, 3, 0], [2, 0, 0]],
        [[2, 0, 0], [2, 0, 4]],
    ]
    for chain, length in zip(chains, [5 + sqrt(13), 4], strict=True):
        assert chain["source_length_mesh_units"] == pytest.approx(length)
        assert chain["length_m"] == pytest.approx(length * 0.01)
        assert chain["length_scale_only_interval_m"] == pytest.approx(
            [length * 0.009, length * 0.011]
        )
        assert chain["human_review_verified"] is False
        assert chain["biological_validation_status"] == "not_verified_anatomical_centerline"
        assert chain["qc_warnings"] == []
    assert union["endpoint_graph_topology"] == {
        "method": "exact_nonzero_edge_endpoint_graph",
        "vertex_count": 4,
        "connected_component_count": 1,
        "degree_one_vertex_count": 1,
        "degree_three_or_more_vertex_count": 1,
        "cycle_rank": 1,
        "biological_validation_status": "not_verified_anatomical_centerline",
        "human_review_verified": False,
    }
    assert union["nonzero_edge_traversal_count"] == (5 if shared else 4)
    assert union["within_trace_redundant_traversal_count"] == 0
    assert union["cross_trace_redundant_traversal_count"] == int(shared)
    assert union["redundant_traversal_source_length_mesh_units"] == (2.0 if shared else 0.0)
    assert union["within_trace_redundant_source_length_mesh_units"] == 0.0
    assert union["cross_trace_redundant_source_length_mesh_units"] == (2.0 if shared else 0.0)
    assert union["cross_trace_shared_source_length_mesh_units"] == (2.0 if shared else 0.0)
    assert union["cross_trace_shared_source_length_fraction"] == pytest.approx(
        2 / source_length if shared else 0.0
    )
    assert union["source_length_mesh_units"] == pytest.approx(source_length)
    assert union["length_m"] == pytest.approx(source_length * 0.01)
    assert union["length_scale_only_interval_m"] == pytest.approx(
        [source_length * 0.009, source_length * 0.011]
    )
    assert union["method"] == "exact_endpoint_pair_equality_only"
    assert union["biological_validation_status"] == "not_verified_anatomical_centerline"
    assert union["human_review_verified"] is False
    assert union["qc_warnings"] == []
    traces = direct["surface_edge_traces"]
    assert [trace["length_m"] for trace in traces] == pytest.approx(expected_lengths)
    assert [trace["vertex_indices"] for trace in traces] == paths
    for trace, length in zip(traces, expected_lengths, strict=True):
        expected_interval = [length * 0.9, length * 1.1]
        assert trace["length_scale_only_interval_m"] == pytest.approx(expected_interval)
        assert trace["biological_validation_status"] == "not_verified_anatomical_centerline"
        assert trace["human_review_verified"] is False

    project_id = str(create_project(client, "Shared trace trunk")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["surface_edge_traces"] == traces
    assert expected["qc_warnings"] == direct["qc_warnings"]
    assert expected["surface_trace_shared_geometric_edge_pairs"] == expected_pairs
    assert expected["surface_trace_exact_edge_union"] == union
    assert expected["provenance"]["calibration_verified"] is False
    graph = {
        "graph_id": "shared-trace-trunk",
        "name": "Provisional overlapping trace selections",
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
    hashes: list[str] = []
    for _ in range(2):
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
        assert artifact["payload_json"]["surface_edge_traces"] == expected["surface_edge_traces"]
        assert artifact["payload_json"]["qc_warnings"] == expected["qc_warnings"]
        payload = artifact["payload_json"]
        assert payload["surface_trace_shared_geometric_edge_pairs"] == expected_pairs
        assert payload["surface_trace_exact_edge_union"] == union
        assert artifact["payload_json"]["provenance"] == expected["provenance"]
        assert len(artifact["payload_sha256"]) == 64
        hashes.append(artifact["payload_sha256"])
    assert hashes[0] == hashes[1]


def test_shared_trace_pairs_count_distinct_edges_not_repeated_traversals() -> None:
    params = {
        **PARAMS,
        "surface_path_vertex_pairs": None,
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0], [1, 0, 0], [1, -1, 0]],
        "faces": [[0, 1, 2], [2, 4, 5], [4, 3, 5]],
        "surface_trace_vertex_paths": [[0, 1, 2, 4, 3], [2, 1, 0], [1, 0]],
    }
    result = measure_mesh_preview(**params)
    assert result["surface_trace_shared_geometric_edge_pairs"] == [
        {"trace_indices": [0, 1], "shared_distinct_geometric_edge_count": 2},
        {"trace_indices": [0, 2], "shared_distinct_geometric_edge_count": 1},
        {"trace_indices": [1, 2], "shared_distinct_geometric_edge_count": 1},
    ]
    assert "surface_traces_share_geometric_edges" in result["qc_warnings"]
    union = result["surface_trace_exact_edge_union"]
    assert union["distinct_nonzero_edge_count"] == 2
    topology = union["endpoint_graph_topology"]
    assert topology["vertex_count"] == 3
    assert topology["connected_component_count"] == 1
    assert topology["degree_one_vertex_count"] == 2
    assert topology["degree_three_or_more_vertex_count"] == 0
    assert topology["cycle_rank"] == 0
    assert union["nonzero_edge_traversal_count"] == 7
    assert union["within_trace_redundant_traversal_count"] == 2
    assert union["cross_trace_redundant_traversal_count"] == 3
    assert union["redundant_traversal_source_length_mesh_units"] == pytest.approx(3 + 2 * sqrt(2))
    # One repeated pass of each edge within the first trace, plus two
    # cross-selection repeats of the unit edge and one of the diagonal.
    assert union["within_trace_redundant_source_length_mesh_units"] == pytest.approx(1 + sqrt(2))
    assert union["cross_trace_redundant_source_length_mesh_units"] == pytest.approx(2 + sqrt(2))
    assert union["cross_trace_shared_source_length_mesh_units"] == pytest.approx(1 + sqrt(2))
    assert union["cross_trace_shared_source_length_fraction"] == 1.0
    assert union["source_length_mesh_units"] == pytest.approx(1 + sqrt(2))
    chains = union["endpoint_graph_chains"]
    _assert_chain_traversals(chains, params["vertices"], params["surface_trace_vertex_paths"])
    assert len(chains) == 1
    assert chains[0]["source_arc_length_by_distinct_trace_count"] == [
        {"distinct_trace_count": 2, "edge_count": 1, "source_length_mesh_units": sqrt(2)},
        {"distinct_trace_count": 3, "edge_count": 1, "source_length_mesh_units": 1.0},
    ]
    assert chains[0]["selected_trace_memberships"] == [
        {"trace_index": 0, "chain_edge_offsets": [0, 1]},
        {"trace_index": 1, "chain_edge_offsets": [0, 1]},
        {"trace_index": 2, "chain_edge_offsets": [0]},
    ]
    assert chains[0]["selected_chain_edge_support"] == [
        {
            "chain_edge_offset": 0,
            "distinct_trace_count": 3,
            "forward_traversal_count": 1,
            "reverse_traversal_count": 3,
        },
        {
            "chain_edge_offset": 1,
            "distinct_trace_count": 2,
            "forward_traversal_count": 1,
            "reverse_traversal_count": 2,
        },
    ]


def test_exact_trace_endpoint_graph_does_not_connect_interior_crossings() -> None:
    # Two edges cross at their interiors, not at selected endpoints.
    # Their graph is disconnected even though the rendered traces intersect.
    params = {
        **PARAMS,
        "surface_path_vertex_pairs": None,
        "vertices": [[-1, 0, 0], [1, 0, 0], [0, 0, 1], [0, -1, 0], [0, 1, 0], [1, 1, 1]],
        "faces": [[0, 1, 2], [3, 4, 5]],
        "surface_trace_vertex_paths": [[0, 1], [4, 3]],
    }
    union = measure_mesh_preview(**params)["surface_trace_exact_edge_union"]
    topology = union["endpoint_graph_topology"]
    assert topology["vertex_count"] == 4
    assert topology["connected_component_count"] == 2
    assert topology["degree_one_vertex_count"] == 4
    assert topology["degree_three_or_more_vertex_count"] == 0
    assert topology["cycle_rank"] == 0
    _assert_endpoint_components(
        union,
        params["vertices"],
        params["surface_trace_vertex_paths"],
        params["meters_per_unit"],
        params["relative_scale_uncertainty"],
    )
    assert union["source_length_mesh_units"] == pytest.approx(4.0)
    chains = union["endpoint_graph_chains"]
    assert [chain["source_waypoints_mesh_units"] for chain in chains] == [
        [[-1, 0, 0], [1, 0, 0]],
        [[0, -1, 0], [0, 1, 0]],
    ]
    assert [chain["length_m"] for chain in chains] == pytest.approx([0.02, 0.02])
    components = union["endpoint_graph_components"]
    assert [component["length_m"] for component in components] == pytest.approx([0.02, 0.02])
    assert [component["axis_aligned_spans_m"] for component in components] == [
        [0.02, 0.0, 0.0],
        [0.0, 0.02, 0.0],
    ]
    assert components[1]["source_axis_aligned_bounds_mesh_units"] == {
        "minimum": [0, -1, 0],
        "maximum": [0, 1, 0],
    }
    for component in components:
        assert component["length_scale_only_interval_m"] == pytest.approx([0.018, 0.022])
    assert topology["human_review_verified"] is False
    assert "surface_trace_cross_component_collinear_overlap" not in union["qc_warnings"]


@pytest.mark.parametrize("scale", [0.001, 0.01, 2.0])
def test_open_chain_straightness_is_scale_and_direction_invariant(scale: float) -> None:
    for path in ([0, 2, 1], [1, 2, 0]):
        result = measure_mesh_preview(
            **{
                **PARAMS,
                "meters_per_unit": scale,
                "surface_trace_vertex_paths": [path],
            }
        )
        chains = result["surface_trace_exact_edge_union"]["endpoint_graph_chains"]
        assert len(chains) == 1
        chain = chains[0]
        assert chain["endpoint_straightness_ratio"] == pytest.approx(1 / (1 + sqrt(2)))
        assert chain["source_endpoint_chord_mesh_units"] == 1.0
        assert chain["endpoint_chord_length_m"] == pytest.approx(scale)
        assert chain["endpoint_chord_length_scale_only_interval_m"] == pytest.approx(
            [scale * 0.9, scale * 1.1]
        )
        assert chain["human_review_verified"] is False
        assert chain["biological_validation_status"] == "not_verified_anatomical_centerline"


@pytest.mark.parametrize("scale", [0.001, 0.01, 2.0])
def test_chain_arc_midpoint_is_source_bound_and_direction_invariant(scale: float) -> None:
    for path in ([0, 2, 1], [1, 2, 0]):
        params = {
            **PARAMS,
            "meters_per_unit": scale,
            "surface_trace_vertex_paths": [path],
        }
        chain = measure_mesh_preview(**params)["surface_trace_exact_edge_union"][
            "endpoint_graph_chains"
        ][0]
        fraction = (sqrt(2) - 1) / (2 * sqrt(2))
        assert chain["source_arc_midpoint_mesh_units"] == pytest.approx(
            [fraction, 1 - fraction, 0.0]
        )
        assert chain["source_arc_midpoint_chain_edge_offset"] == 1
        assert chain["source_longest_edge_chain_offset"] == 1
        assert chain["source_longest_edge_arc_fraction"] == pytest.approx(sqrt(2) / (1 + sqrt(2)))
        assert chain["source_arc_centroid_mesh_units"] == pytest.approx(
            [sqrt(2) / (2 * (1 + sqrt(2))), 0.5, 0.0]
        )
        assert chain["human_review_verified"] is False


def test_chain_arc_midpoint_at_shared_vertex_uses_earlier_edge() -> None:
    params = {
        **PARAMS,
        "vertices": [[0, 0, 0], [1, 0, 0], [1, 1, 0]],
        "surface_trace_vertex_paths": [[2, 1, 0]],
    }
    chain = measure_mesh_preview(**params)["surface_trace_exact_edge_union"][
        "endpoint_graph_chains"
    ][0]
    assert chain["source_arc_midpoint_mesh_units"] == [1.0, 0.0, 0.0]
    assert chain["source_arc_midpoint_chain_edge_offset"] == 0
    assert chain["source_arc_midpoint_edge_fraction"] == {"numerator": "1", "denominator": "1"}
    assert chain["source_longest_edge_chain_offset"] == 0
    assert chain["source_longest_edge_arc_fraction"] == 0.5
    assert chain["biological_validation_status"] == "not_verified_anatomical_centerline"


def test_chain_geometry_digest_is_source_bound_not_calibration_or_signed_zero() -> None:
    baseline = measure_mesh_preview(**PARAMS)["surface_trace_exact_edge_union"]
    expected = baseline["endpoint_graph_chains"][0]["source_chain_geometry_sha256"]
    params = {
        **PARAMS,
        "vertices": [[-0.0, -0.0, 0.0], [1, -0.0, 0.0], [-0.0, 1, -0.0]],
        "surface_trace_vertex_paths": [[1, 2, 0]],
        "meters_per_unit": 0.5,
        "relative_scale_uncertainty": None,
    }
    reversed_union = measure_mesh_preview(**params)["surface_trace_exact_edge_union"]
    reversed_chain = reversed_union["endpoint_graph_chains"][0]
    assert reversed_chain["source_chain_geometry_sha256"] == expected
    assert reversed_chain["length_m"] == pytest.approx(0.5 * (1 + sqrt(2)))
    params["vertices"] = [[0, 0, 0], [1, 0, 0], [0, 2, 0]]
    changed = measure_mesh_preview(**params)["surface_trace_exact_edge_union"]
    assert changed["endpoint_graph_chains"][0]["source_chain_geometry_sha256"] != expected


def test_component_geometry_digest_is_source_bound_not_calibration_or_signed_zero() -> None:
    baseline = measure_mesh_preview(**PARAMS)["surface_trace_exact_edge_union"]
    digest = baseline["endpoint_graph_components"][0]["source_component_geometry_sha256"]
    assert digest == "e29615108a563192ae7a8d8f162a3548e4e684002489ccde85d757cdeb31e43f"
    params = {
        **PARAMS,
        "vertices": [[-0.0, -0.0, 0.0], [1, -0.0, 0.0], [-0.0, 1, -0.0]],
        "surface_trace_vertex_paths": [[1, 2, 0], [0, 2]],
        "meters_per_unit": 0.5,
        "relative_scale_uncertainty": None,
    }
    reversed_union = measure_mesh_preview(**params)["surface_trace_exact_edge_union"]
    component = reversed_union["endpoint_graph_components"][0]
    assert component["source_component_geometry_sha256"] == digest
    assert component["source_endpoint_graph_landmarks"] == [
        {"source_vertex_mesh_units": [0.0, 0.0, 0.0], "degree": 1},
        {"source_vertex_mesh_units": [1.0, 0.0, 0.0], "degree": 1},
    ]
    assert all(
        "-0.0" not in json.dumps(item["source_vertex_mesh_units"])
        for item in component["source_endpoint_graph_landmarks"]
    )
    assert component["length_m"] == pytest.approx(0.5 * (1 + sqrt(2)))
    assert component["axis_aligned_spans_m"] == [0.5, 0.5, 0.0]
    assert component["axis_aligned_span_scale_only_intervals_m"] == [None, None, None]
    assert "-0.0" not in json.dumps(component["source_axis_aligned_bounds_mesh_units"])
    params["surface_trace_vertex_paths"] = [[0, 1, 2]]
    changed = measure_mesh_preview(**params)["surface_trace_exact_edge_union"]
    assert changed["endpoint_graph_components"][0]["source_component_geometry_sha256"] != digest


def test_unequal_collinear_overlap_counts_distinct_pairs_in_three_dimensions() -> None:
    # Along (1, 2, 3), intervals [0, 4], [1, 3], [2, 5] overlap pairwise.
    # [5, 6] touches only the third. A parallel offset line does not overlap.
    vertices = [[i, 2 * i, 3 * i] for i in range(7)]
    vertices.extend([[0, 1, 0], [4, 9, 12], [0, 0, 10]])
    paths = [[0, 4], [3, 1], [2, 5], [5, 6], [7, 8], [4, 0]]
    faces = [[a, b, 9] for a, b in paths[:-1]]
    params = {
        **PARAMS,
        "vertices": vertices,
        "faces": faces,
        "surface_path_vertex_pairs": None,
        "surface_trace_vertex_paths": paths,
    }
    for scale in (0.01, 2.0):
        result = measure_mesh_preview(**{**params, "meters_per_unit": scale})
        union = result["surface_trace_exact_edge_union"]
        assert union["unequal_collinear_overlap_pair_count"] == 3
        assert union["cross_component_unequal_collinear_overlap_pair_count"] == 3
        warning = "surface_trace_cross_component_collinear_overlap"
        assert union["qc_warnings"].count(warning) == 1
        assert result["qc_warnings"].count(warning) == 1
        assert union["distinct_nonzero_edge_count"] == 5
        assert union["nonzero_edge_traversal_count"] == 6
        assert union["source_length_mesh_units"] == pytest.approx(14 * sqrt(14))
        corrected = union["collinear_overlap_corrected_union"]
        assert corrected["source_length_mesh_units"] == pytest.approx(10 * sqrt(14))
        assert corrected["length_m"] == pytest.approx(10 * sqrt(14) * scale)
        assert corrected["length_scale_only_interval_m"] == pytest.approx(
            [9 * sqrt(14) * scale, 11 * sqrt(14) * scale]
        )
        assert corrected["human_review_verified"] is False
        assert union["human_review_verified"] is False


@pytest.mark.parametrize("uncertainty", [None, 0.0, 1e-30, 0.1, 1.0])
def test_trace_union_numeric_qc_is_visible_at_preview_level(uncertainty: float | None) -> None:
    result = measure_mesh_preview(**{**PARAMS, "relative_scale_uncertainty": uncertainty})
    union = result["surface_trace_exact_edge_union"]
    corrected = union["collinear_overlap_corrected_union"]
    assert corrected["length_m"] == pytest.approx(0.01 * (1 + sqrt(2)))
    warnings = {
        "surface_trace_exact_edge_union_interval_unrepresentable",
        "surface_trace_collinear_union_interval_unrepresentable",
        "surface_trace_chain_interval_unrepresentable",
        "surface_trace_chain_chord_interval_unrepresentable",
        "surface_trace_component_interval_unrepresentable",
        "surface_trace_component_axis_span_interval_unrepresentable",
    }
    expected_warnings = warnings if uncertainty == 1e-30 else set()
    assert warnings.intersection(result["qc_warnings"]) == expected_warnings
    component = union["endpoint_graph_components"][0]
    assert component["axis_aligned_spans_m"] == [0.01, 0.01, 0.0]
    span_intervals = component["axis_aligned_span_scale_only_intervals_m"]
    if uncertainty is None:
        assert span_intervals == [None, None, None]
    elif uncertainty == 1e-30:
        assert span_intervals == [None, None, [0.0, 0.0]]
    else:
        for interval in span_intervals[:2]:
            assert interval == pytest.approx([0.01 * (1 - uncertainty), 0.01 * (1 + uncertainty)])
        assert span_intervals[2] == [0.0, 0.0]
    chain = union["endpoint_graph_chains"][0]
    assert chain["endpoint_chord_length_m"] == pytest.approx(0.01)
    if uncertainty is None or uncertainty == 1e-30:
        assert chain["endpoint_chord_length_scale_only_interval_m"] is None
    else:
        assert chain["endpoint_chord_length_scale_only_interval_m"] == pytest.approx(
            [0.01 * (1 - uncertainty), 0.01 * (1 + uncertainty)]
        )
    if uncertainty is None or uncertainty == 1e-30:
        assert corrected["length_scale_only_interval_m"] is None
    else:
        length = corrected["length_m"]
        assert corrected["length_scale_only_interval_m"] == pytest.approx(
            [length * (1 - uncertainty), length * (1 + uncertainty)]
        )
    assert corrected["human_review_verified"] is False
