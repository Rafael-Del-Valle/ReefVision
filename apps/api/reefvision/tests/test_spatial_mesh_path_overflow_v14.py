"""Numerical integrity for provisional mesh-edge path accumulation."""

import pytest

from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths


def test_finite_individual_edges_cannot_silently_overflow_total_path() -> None:
    # Each triangle edge is finite, but the only route from 0 to 3
    # traverses two ~1e308-unit edges. An infinite Dijkstra candidate
    # must not be mistaken for a disconnected mesh.
    points = [
        (-1e308, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (-5e307, 1.0, 0.0),
        (1e308, 0.0, 0.0),
        (5e307, 1.0, 0.0),
    ]
    faces = [[0, 1, 2], [1, 3, 4]]
    with pytest.raises(ValueError, match="Accumulated mesh path length overflowed"):
        mesh_edge_paths(points, faces, [[0, 3]], 1.0, None)



def test_overflowing_detour_before_destination_discovery_does_not_hide_valid_path() -> None:
    # Popping vertex 1 before vertex 2 first encounters the reverse edge to
    # vertex 0: 1e308 + 1e308 overflows, although vertex 3 is still reachable
    # through finite, representable accumulated costs. This previously raised
    # before Dijkstra could discover the valid destination.
    points = [
        (0.0, 0.0, 0.0),
        (1e308, 0.0, 0.0),
        (1e308, 1.0, 0.0),
        (1e308, 2.0, 1.0),
    ]
    paths = mesh_edge_paths(points, [[0, 1, 2], [1, 2, 3]], [[0, 3]], 0.1, 0.1)
    assert paths is not None
    path = paths[0]
    assert path["status"] == "connected"
    assert path["length_m"] == pytest.approx(1e307)
    assert path["path_vertex_indices"] is not None
    assert path["path_vertex_indices"][0] == 0
    assert path["path_vertex_indices"][-1] == 3
    assert path["shortest_route_alternatives_status"] == (
        "unassessable_floating_point_cost_resolution"
    )
    assert "positive_mesh_edge_cost_rounded_away" in path["path_qc_warnings"]


def test_unrelated_overflow_does_not_turn_disconnected_components_into_errors() -> None:
    # The explored component contains a candidate 1e308 + 1e308 overflow.
    # An endpoint in a different connected component is still disconnected,
    # not an unrepresentable connected shortest path.
    points = [
        (0.0, 0.0, 0.0),
        (1e308, 0.0, 0.0),
        (1e308, 1.0, 0.0),
        (4.0, 0.0, 0.0),
        (5.0, 0.0, 0.0),
        (4.0, 1.0, 0.0),
    ]
    paths = mesh_edge_paths(points, [[0, 1, 2], [3, 4, 5]], [[0, 3]], 1.0, None)
    assert paths is not None
    assert paths[0]["status"] == "disconnected"
    assert paths[0]["length_m"] is None
    assert paths[0]["shortest_route_alternatives_status"] is None


def test_calibrated_route_vertices_reject_coordinate_overflow() -> None:
    # Local edge distances remain representable after calibration, while
    # absolute source-frame coordinates cannot be represented in meters.
    # Keep this triangle collinear so cross-product overflow is not the
    # earlier, independent rejection reason being exercised here.
    points = [
        (1e300, 0.0, 0.0),
        (1e300 + 1e290, 0.0, 0.0),
        (1e300 + 2e290, 0.0, 0.0),
    ]
    with pytest.raises(ValueError, match="Calibrated mesh path vertex coordinate overflowed"):
        mesh_edge_paths(points, [[0, 1, 2]], [[0, 1]], 1e10, None)
