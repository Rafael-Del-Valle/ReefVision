"""Geometry and identity rules for append-only coral graph review."""

from collections.abc import Sequence
from dataclasses import replace
from math import hypot
from uuid import uuid4

from reefvision.schemas.coral_graph import BranchSupersession, GraphEdit, GraphSnapshot
from reefvision.schemas.skeletonization import SkeletonPixelEdit
from reefvision.services.connected_branch_editing import (
    BranchEditError,
    Pixel,
    _checked_path,
    _edge,
    _new_endpoint,
    preview_connected_branch_addition,
    validate_branch_graph,
)
from reefvision.services.skeleton_algorithms import SkeletonGraphEdge, SkeletonGraphNode


def pixel(point: SkeletonPixelEdit) -> Pixel:
    return (point.x, point.y)


def restore_graph(
    snapshot: GraphSnapshot,
) -> tuple[list[SkeletonGraphNode], list[SkeletonGraphEdge]]:
    return (
        [
            SkeletonGraphNode(
                node.id,
                node.kind,
                node.x,
                node.y,
                tuple(map(pixel, node.source_pixels)),
                node.external_connection_count,
            )
            for node in snapshot.nodes
        ],
        [
            SkeletonGraphEdge(
                edge.id,
                edge.source_node_id,
                edge.target_node_id,
                tuple(map(pixel, edge.pixels)),
                edge.boundary_to_boundary_length_pixels,
                edge.node_to_node_length_pixels,
                edge.is_cycle,
            )
            for edge in snapshot.edges
        ],
    )


def assign_ids(
    nodes: Sequence[SkeletonGraphNode],
    edges: Sequence[SkeletonGraphEdge],
    known_nodes: set[str] | None = None,
    known_edges: set[str] | None = None,
) -> tuple[list[SkeletonGraphNode], list[SkeletonGraphEdge], dict[str, str]]:
    node_ids = {
        node.id: node.id if known_nodes and node.id in known_nodes else str(uuid4())
        for node in nodes
    }
    edge_ids = {
        edge.id: edge.id if known_edges and edge.id in known_edges else str(uuid4())
        for edge in edges
    }
    return (
        [replace(node, id=node_ids[node.id]) for node in nodes],
        [
            replace(
                edge,
                id=edge_ids[edge.id],
                source_node_id=node_ids[edge.source_node_id],
                target_node_id=node_ids[edge.target_node_id],
            )
            for edge in edges
        ],
        edge_ids,
    )


def _orient(edge: SkeletonGraphEdge, from_id: str) -> tuple[Pixel, ...]:
    return edge.pixels if edge.source_node_id == from_id else edge.pixels[::-1]


def _snap_path(
    points: tuple[Pixel, ...], occupied: set[Pixel], tolerance: float
) -> tuple[Pixel, ...]:
    if points[0] in occupied or not tolerance or not occupied:
        return points
    x, y = points[0]
    distances = [(hypot(px - x, py - y), (px, py)) for px, py in occupied]
    nearest = min(distance for distance, _ in distances)
    if nearest > tolerance:
        return points
    matches = [candidate for distance, candidate in distances if distance == nearest]
    if len(matches) != 1:
        raise BranchEditError("Multiple nearest attachments; select an exact source pixel")
    return (matches[0], *points[1:])


def apply_graph_edit(
    nodes: list[SkeletonGraphNode], edges: list[SkeletonGraphEdge], edit: GraphEdit
) -> tuple[
    list[SkeletonGraphNode], list[SkeletonGraphEdge], list[BranchSupersession], Pixel | None
]:
    nodes_by_id, occupied = validate_branch_graph(nodes, edges)
    edges_by_id = {edge.id: edge for edge in edges}
    if not set(edit.branch_ids).issubset(edges_by_id):
        raise BranchEditError("Select branches from the current reviewed revision")
    points = tuple(map(pixel, edit.points))
    selected = [edges_by_id[key] for key in edit.branch_ids]
    affected = list(edit.branch_ids)
    successors: list[SkeletonGraphEdge] = []
    attachment = None
    if edit.kind == "add":
        points = _snap_path(points, occupied, edit.snap_tolerance_px)
        proposal = preview_connected_branch_addition(nodes, edges, points, edit_id=uuid4().hex)
        new_nodes, new_edges, ids = assign_ids(
            proposal.nodes, proposal.edges, set(nodes_by_id), set(edges_by_id)
        )
        lineage = (
            [
                BranchSupersession(
                    previous_branch_ids=list(proposal.superseded_edge_ids),
                    successor_branch_ids=[ids[key] for key in proposal.replacement_edge_ids],
                )
            ]
            if proposal.superseded_edge_ids
            else []
        )
        return new_nodes, new_edges, lineage, points[0] if proposal.attached_node_id else None
    if edit.kind == "split":
        edge = selected[0]
        point = points[0]
        if point not in edge.pixels[1:-1] or any(point in node.source_pixels for node in nodes):
            raise BranchEditError("Split at an interior source pixel of the selected branch")
        index = edge.pixels.index(point)
        junction = _new_endpoint(str(uuid4()), point, kind="junction")
        nodes = [*nodes, junction]
        successors = [
            _edge(
                str(uuid4()), nodes_by_id[edge.source_node_id], junction, edge.pixels[: index + 1]
            ),
            _edge(str(uuid4()), junction, nodes_by_id[edge.target_node_id], edge.pixels[index:]),
        ]
        attachment = point
    elif edit.kind == "merge":
        first, second = selected
        joint = {first.source_node_id, first.target_node_id} & {
            second.source_node_id,
            second.target_node_id,
        }
        if len(joint) != 1 or first.is_cycle or second.is_cycle:
            raise BranchEditError("Merging requires two non-cycle branches at one junction")
        junction_id = next(iter(joint))
        junction = nodes_by_id[junction_id]
        degree = sum(
            (edge.source_node_id == junction_id) + (edge.target_node_id == junction_id)
            for edge in edges
        )
        if degree != 2 or len(junction.source_pixels) != 1:
            raise BranchEditError("Merge only at a degree-two, single-pixel junction")
        outer = [{edge.source_node_id, edge.target_node_id} - joint for edge in selected]
        start, end = (nodes_by_id[next(iter(ids))] for ids in outer)
        path = (*reversed(_orient(first, junction_id)), *_orient(second, junction_id)[1:])
        successors = [_edge(str(uuid4()), start, end, path)]
        attachment = junction.source_pixels[0]
    elif edit.kind == "correct":
        original = selected[0]
        start = nodes_by_id[original.source_node_id]
        end = nodes_by_id[original.target_node_id]
        path = _checked_path(points)
        if path[0] not in start.source_pixels or path[-1] not in end.source_pixels:
            raise BranchEditError(
                "Corrected centerline must connect the original junctions in order"
            )
        other_pixels = {
            point for edge in edges if edge.id != original.id for point in edge.pixels
        } | {point for node in nodes for point in node.source_pixels}
        if other_pixels.intersection(path[1:-1]):
            raise BranchEditError("Corrected centerline crosses another branch or junction")
        successors = [_edge(str(uuid4()), start, end, path)]

    edges = [edge for edge in edges if edge.id not in affected] + successors
    if not edges:
        raise BranchEditError("Keep at least one measurable branch in the colony graph")
    degree_by_id: dict[str, int] = {}
    for edge in edges:
        for endpoint in (edge.source_node_id, edge.target_node_id):
            degree_by_id[endpoint] = degree_by_id.get(endpoint, 0) + 1
    nodes = [
        replace(
            node,
            kind="endpoint" if degree_by_id[node.id] == 1 else "junction",
            external_connection_count=degree_by_id[node.id],
        )
        for node in nodes
        if node.id in degree_by_id
    ]
    validate_branch_graph(nodes, edges)
    return (
        nodes,
        edges,
        [
            BranchSupersession(
                previous_branch_ids=affected, successor_branch_ids=[edge.id for edge in successors]
            )
        ],
        attachment,
    )


def match_unchanged_geometry(
    nodes: list[SkeletonGraphNode], edges: list[SkeletonGraphEdge], prior: GraphSnapshot
) -> tuple[list[SkeletonGraphNode], list[SkeletonGraphEdge], list[BranchSupersession]]:
    """Carry stable IDs to an updated source only for exact identical geometry."""
    old_nodes, old_edges = restore_graph(prior)
    prior_nodes = {tuple(sorted(node.source_pixels)): node.id for node in old_nodes}
    node_map = {
        node.id: prior_nodes.get(tuple(sorted(node.source_pixels)), str(uuid4())) for node in nodes
    }

    def signature(edge: SkeletonGraphEdge) -> tuple[str, str, tuple[Pixel, ...]]:
        forward = (edge.source_node_id, edge.target_node_id, edge.pixels)
        backward = (edge.target_node_id, edge.source_node_id, edge.pixels[::-1])
        return min(forward, backward)

    previous = {signature(edge): edge.id for edge in old_edges}
    remapped = []
    for edge in edges:
        current = replace(
            edge,
            source_node_id=node_map[edge.source_node_id],
            target_node_id=node_map[edge.target_node_id],
        )
        remapped.append(replace(current, id=previous.get(signature(current), str(uuid4()))))
    retained = {edge.id for edge in remapped}
    retired = [edge.id for edge in old_edges if edge.id not in retained]
    return (
        [replace(node, id=node_map[node.id]) for node in nodes],
        remapped,
        [BranchSupersession(previous_branch_ids=retired, successor_branch_ids=[])]
        if retired
        else [],
    )
