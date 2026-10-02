import pytest

from reefvision.services.skeleton_algorithms import (
    build_initial_branch_graph,
    classify_skeleton_pixels,
    consolidate_junction_clusters,
)


def _mask(
    width: int,
    height: int,
    foreground: set[tuple[int, int]],
) -> tuple[bytes, int, int]:
    data = bytearray(width * height)
    for x, y in foreground:
        data[y * width + x] = 255
    return bytes(data), width, height


def test_simple_path_becomes_two_nodes_and_one_branch() -> None:
    features = classify_skeleton_pixels(
        _mask(7, 5, {(x, 2) for x in range(1, 6)})
    )

    nodes, edges = build_initial_branch_graph(features, [])

    assert [node.kind for node in nodes] == ["endpoint", "endpoint"]
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_node_id == "endpoint-0001"
    assert edge.target_node_id == "endpoint-0002"
    assert len(edge.pixels) == 5
    assert edge.boundary_to_boundary_length_pixels == pytest.approx(4.0)
    assert edge.is_cycle is False


def test_cross_uses_one_consolidated_junction_and_four_branches() -> None:
    foreground = {
        (3, 1),
        (3, 2),
        (3, 3),
        (3, 4),
        (3, 5),
        (1, 3),
        (2, 3),
        (4, 3),
        (5, 3),
    }
    features = classify_skeleton_pixels(_mask(7, 7, foreground))
    clusters = consolidate_junction_clusters(features)

    nodes, edges = build_initial_branch_graph(features, clusters)

    assert len(clusters) == 1
    assert sum(node.kind == "junction" for node in nodes) == 1
    assert sum(node.kind == "endpoint" for node in nodes) == 4
    assert len(edges) == 4
    assert all(
        "junction-0001" in {edge.source_node_id, edge.target_node_id}
        for edge in edges
    )
    assert all(edge.boundary_to_boundary_length_pixels == pytest.approx(1.0) for edge in edges)
    assert all(edge.is_cycle is False for edge in edges)


def test_single_pixel_skeleton_is_preserved_as_isolated_graph_node() -> None:
    features = classify_skeleton_pixels(_mask(3, 3, {(1, 1)}))

    nodes, edges = build_initial_branch_graph(features, [])

    assert len(nodes) == 1
    assert nodes[0].id == "isolated-0001"
    assert nodes[0].kind == "isolated"
    assert edges == []
