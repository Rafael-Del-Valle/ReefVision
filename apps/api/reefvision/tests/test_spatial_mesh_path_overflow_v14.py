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
