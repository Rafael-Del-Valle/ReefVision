"""1.2 connected branch edit preview regressions: no silent links or length loss."""

from dataclasses import replace

import pytest

from reefvision.services.connected_branch_editing import (
    BranchEditError,
    preview_connected_branch_addition,
)
from reefvision.services.skeleton_algorithms import (
    SkeletonGraphEdge,
    SkeletonGraphNode,
    build_initial_branch_graph,
    classify_skeleton_pixels,
)


def _line() -> tuple[list, list]:
    width, height = 8, 6
    data = bytearray(width * height)
    for x in range(1, 6):
        data[2 * width + x] = 255
    return build_initial_branch_graph(classify_skeleton_pixels((bytes(data), width, height)), [])


def test_initial_root_segment_is_proposed_not_accepted() -> None:
    result = preview_connected_branch_addition([], [], [(1, 1), (2, 1), (3, 1)], edit_id="a")
    assert result.attached_node_id is None
    assert len(result.nodes) == 2
    assert len(result.edges) == 1
    assert result.review_required is True
    assert result.proposed_total_length_pixels == pytest.approx(2.0)


def test_interior_attachment_splits_original_edge_without_length_loss() -> None:
    nodes, edges = _line()
    original = edges[0]
    result = preview_connected_branch_addition(
        nodes, edges, [(3, 2), (3, 3), (3, 4)], edit_id="first"
    )
    assert original.id == "branch-0001"
    assert result.superseded_edge_ids == (original.id,)
    assert result.replacement_edge_ids == (
        "manual-first-upstream",
        "manual-first-downstream",
    )
    assert len(result.nodes) == 4
    assert len(result.edges) == 3
    assert result.original_total_length_pixels == pytest.approx(4.0)
    assert result.added_length_pixels == pytest.approx(2.0)
    assert result.proposed_total_length_pixels == pytest.approx(6.0)
    lengths = sorted(edge.node_to_node_length_pixels for edge in result.edges)
    assert lengths == pytest.approx([2.0, 2.0, 2.0])
    assert len(edges) == 1  # existing source graph is never changed
    assert original.id not in {edge.id for edge in result.edges}


def test_attachment_to_existing_endpoint_keeps_original_edge_identity() -> None:
    nodes, edges = _line()
    result = preview_connected_branch_addition(
        nodes, edges, [(1, 2), (1, 3), (1, 4)], edit_id="endpoint"
    )
    assert result.attached_node_id == "endpoint-0001"
    assert result.superseded_edge_ids == ()
    assert {edge.id for edge in result.edges} == {"branch-0001", "manual-endpoint-branch"}
    assert result.proposed_total_length_pixels == pytest.approx(6.0)


def test_second_branch_attaches_to_created_junction() -> None:
    nodes, edges = _line()
    first = preview_connected_branch_addition(nodes, edges, [(3, 2), (3, 3), (3, 4)], edit_id="one")
    second = preview_connected_branch_addition(
        first.nodes, first.edges, [(3, 2), (4, 3), (5, 4)], edit_id="two"
    )
    assert second.attached_node_id == "manual-one-root"
    assert second.superseded_edge_ids == ()
    assert second.proposed_total_length_pixels == pytest.approx(6.0 + 2 * 2**0.5)


@pytest.mark.parametrize(
    "path",
    [
        [(3, 1), (3, 0)],  # disconnected, despite being only one pixel away
        [(1, 2), (2, 2)],  # overlaps the original edge
        [(3, 2), (3, 2)],  # repeated pixel
        [(3, 2), (3, 4)],  # unseen gap; never automatically bridge
        [(3, 2), (3, 3), (3, 2)],  # duplicated walk
        [(3, 2)],  # incomplete candidate
    ],
)
def test_disconnected_overlapping_or_invalid_path_is_rejected(path: list) -> None:
    nodes, edges = _line()
    with pytest.raises(BranchEditError):
        preview_connected_branch_addition(nodes, edges, path, edit_id="reject")


def test_existing_graph_ids_must_be_unique() -> None:
    nodes, edges = _line()
    with pytest.raises(BranchEditError, match="duplicate"):
        preview_connected_branch_addition(nodes, [*edges, edges[0]], [(1, 2), (1, 3)], edit_id="x")


def test_reusing_an_edit_id_is_blocked() -> None:
    nodes, edges = _line()
    first = preview_connected_branch_addition(nodes, edges, [(1, 2), (1, 3)], edit_id="once")
    with pytest.raises(BranchEditError, match="collides"):
        preview_connected_branch_addition(
            first.nodes, first.edges, [(5, 2), (5, 3)], edit_id="once"
        )


def test_existing_source_segment_must_be_pixel_connected() -> None:
    nodes, edges = _line()
    # The forged source keeps the original measured length even though
    # its recorded path jumps over a missing pixel.
    disconnected = replace(
        edges[0],
        pixels=((1, 2), (2, 2), (4, 2), (5, 2)),
    )
    with pytest.raises(BranchEditError, match="disconnected pixel step"):
        preview_connected_branch_addition(nodes, [disconnected], [(3, 2), (3, 3)], edit_id="gap")


def test_existing_source_segment_endpoints_must_match_graph_nodes() -> None:
    nodes, edges = _line()
    # A plausible length checksum alone cannot authenticate graph attachment.
    shifted = replace(
        edges[0],
        pixels=((2, 2), (3, 2), (4, 2), (5, 2)),
        boundary_to_boundary_length_pixels=3.0,
        node_to_node_length_pixels=4.0,
    )
    with pytest.raises(BranchEditError, match="endpoints do not match"):
        preview_connected_branch_addition(
            nodes, [shifted], [(3, 2), (3, 3)], edit_id="misattributed"
        )


def test_existing_segment_revisited_pixels_cannot_inflate_branch_length() -> None:
    nodes, edges = _line()
    # This path has valid endpoints and adjacent steps, and its forged length
    # matches the path sum, but it traverses the same biological segment twice.
    repeated = replace(
        edges[0],
        pixels=((1, 2), (2, 2), (3, 2), (2, 2), (3, 2), (4, 2), (5, 2)),
        boundary_to_boundary_length_pixels=6.0,
        node_to_node_length_pixels=6.0,
    )
    with pytest.raises(BranchEditError, match="revisits a pixel"):
        preview_connected_branch_addition(nodes, [repeated], [(3, 2), (3, 3)], edit_id="repeated")


def test_existing_segment_cycle_flag_must_match_graph_identity() -> None:
    nodes, edges = _line()
    forged_cycle = replace(edges[0], is_cycle=True)
    with pytest.raises(BranchEditError, match="cycle flag"):
        preview_connected_branch_addition(
            nodes, [forged_cycle], [(3, 2), (3, 3)], edit_id="false-cycle"
        )


def test_real_closed_cycle_may_repeat_only_its_terminal_anchor() -> None:
    node = SkeletonGraphNode(
        id="cycle-0001",
        kind="cycle_anchor",
        x=2.0,
        y=1.0,
        source_pixels=((2, 1),),
        external_connection_count=2,
    )
    pixels = ((2, 1), (3, 2), (2, 3), (1, 2), (2, 1))
    length = 4 * 2**0.5
    edge = SkeletonGraphEdge(
        id="branch-0001",
        source_node_id=node.id,
        target_node_id=node.id,
        pixels=pixels,
        boundary_to_boundary_length_pixels=length,
        node_to_node_length_pixels=length,
        is_cycle=True,
    )
    result = preview_connected_branch_addition(
        [node], [edge], [(2, 1), (2, 0), (3, 0)], edit_id="real-cycle"
    )
    assert result.original_total_length_pixels == pytest.approx(length)
    assert result.proposed_total_length_pixels == pytest.approx(length + 2.0)
    assert result.review_required is True


@pytest.mark.parametrize("reverse", [False, True])
def test_existing_segments_cannot_count_a_pixel_step_twice(reverse: bool) -> None:
    nodes, edges = _line()
    original = edges[0]
    duplicate = replace(
        original,
        id="branch-duplicate",
        source_node_id=original.target_node_id if reverse else original.source_node_id,
        target_node_id=original.source_node_id if reverse else original.target_node_id,
        pixels=tuple(reversed(original.pixels)) if reverse else original.pixels,
    )
    proposed = [(1, 2), (1, 3)]
    existing = [original, duplicate]
    with pytest.raises(BranchEditError, match="same skeleton pixel step"):
        preview_connected_branch_addition(nodes, existing, proposed, edit_id="overlap")
