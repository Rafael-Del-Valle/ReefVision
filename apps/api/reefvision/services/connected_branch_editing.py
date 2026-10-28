"""Non-destructive previews for connected 2D coral branch additions.

The graph uses *segments between graph nodes*, not biological branch identities.
This module changes neither persisted skeleton revisions nor reviewed observations.
An explicit review/persistence workflow must accept a preview before research use.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from math import hypot, isclose, isfinite

from reefvision.services.skeleton_algorithms import (
    SkeletonGraphEdge,
    SkeletonGraphNode,
    total_graph_length_pixels,
)

Pixel = tuple[int, int]


class BranchEditError(ValueError):
    """An edit fails connected topology or source-geometry validation."""


@dataclass(frozen=True, slots=True)
class ConnectedBranchPreview:
    """An unverified, ephemeral branch edit; no source record has been changed."""

    nodes: tuple[SkeletonGraphNode, ...]
    edges: tuple[SkeletonGraphEdge, ...]
    attached_node_id: str | None
    added_edge_id: str
    superseded_edge_ids: tuple[str, ...]
    replacement_edge_ids: tuple[str, ...]
    original_total_length_pixels: float
    proposed_total_length_pixels: float
    added_length_pixels: float
    review_required: bool = True


def _checked_path(path: Sequence[Pixel]) -> tuple[Pixel, ...]:
    if len(path) < 2:
        raise BranchEditError("A branch needs at least two distinct connected pixels")
    pixels: list[Pixel] = []
    for point in path:
        if (
            not isinstance(point, tuple)
            or len(point) != 2
            or any(type(value) is not int or value < 0 for value in point)
        ):
            raise BranchEditError("Branch path must contain nonnegative integer (x, y) pixels")
        pixels.append(point)
    if len(set(pixels)) != len(pixels):
        raise BranchEditError("A branch path cannot revisit a pixel or overlap itself")
    for (ax, ay), (bx, by) in pairwise(pixels):
        dx, dy = abs(bx - ax), abs(by - ay)
        if max(dx, dy) != 1:
            raise BranchEditError("Branch path must use contiguous 8-neighbor pixel steps")
    return tuple(pixels)


def _length(pixels: Sequence[Pixel]) -> float:
    return sum(hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in pairwise(pixels))


def _new_endpoint(identifier: str, pixel: Pixel, *, kind: str = "endpoint") -> SkeletonGraphNode:
    # This helper is limited to the two node kinds created by manual edits.
    if kind not in {"endpoint", "junction"}:
        raise BranchEditError("Unsupported manual graph-node kind")
    return SkeletonGraphNode(
        id=identifier,
        kind="junction" if kind == "junction" else "endpoint",
        x=float(pixel[0]),
        y=float(pixel[1]),
        source_pixels=(pixel,),
        external_connection_count=3 if kind == "junction" else 1,
    )


def _edge(
    identifier: str,
    source: SkeletonGraphNode,
    target: SkeletonGraphNode,
    pixels: tuple[Pixel, ...],
) -> SkeletonGraphEdge:
    raw = _length(pixels)
    first_offset = hypot(pixels[0][0] - source.x, pixels[0][1] - source.y)
    last_offset = hypot(pixels[-1][0] - target.x, pixels[-1][1] - target.y)
    return SkeletonGraphEdge(
        id=identifier,
        source_node_id=source.id,
        target_node_id=target.id,
        pixels=pixels,
        boundary_to_boundary_length_pixels=raw,
        node_to_node_length_pixels=raw + first_offset + last_offset,
        is_cycle=source.id == target.id,
    )


def _validate_graph(
    nodes: Sequence[SkeletonGraphNode], edges: Sequence[SkeletonGraphEdge]
) -> tuple[dict[str, SkeletonGraphNode], set[Pixel]]:
    node_by_id = {node.id: node for node in nodes}
    if len(node_by_id) != len(nodes) or len({edge.id for edge in edges}) != len(edges):
        raise BranchEditError("Existing graph has duplicate node or segment IDs")
    occupied: set[Pixel] = set()
    for node in nodes:
        if not isfinite(node.x) or not isfinite(node.y):
            raise BranchEditError("Existing graph contains a nonfinite graph-node coordinate")
        occupied.update(node.source_pixels)
    adjacency: dict[str, set[str]] = {node.id: set() for node in nodes}
    for edge in edges:
        source, target = node_by_id.get(edge.source_node_id), node_by_id.get(edge.target_node_id)
        if source is None or target is None:
            raise BranchEditError("Existing segment references an unknown graph node")
        if len(edge.pixels) < 2:
            raise BranchEditError("Existing segment has no measurable pixel path")
        expected = _edge(edge.id, source, target, edge.pixels)
        if not all(
            isfinite(value) and isclose(value, expected_value, rel_tol=1e-7, abs_tol=1e-7)
            for value, expected_value in (
                (
                    edge.boundary_to_boundary_length_pixels,
                    expected.boundary_to_boundary_length_pixels,
                ),
                (edge.node_to_node_length_pixels, expected.node_to_node_length_pixels),
            )
        ):
            raise BranchEditError("Existing segment geometry and measured length disagree")
        occupied.update(edge.pixels)
        adjacency[source.id].add(target.id)
        adjacency[target.id].add(source.id)
    if nodes:
        visited = {nodes[0].id}
        frontier = [nodes[0].id]
        while frontier:
            for neighbor in adjacency[frontier.pop()]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)
        if len(visited) != len(nodes):
            raise BranchEditError("Existing graph is disconnected; resolve it before editing")
    return node_by_id, occupied


def preview_connected_branch_addition(
    nodes: Sequence[SkeletonGraphNode],
    edges: Sequence[SkeletonGraphEdge],
    branch_pixels: Sequence[Pixel],
    *,
    edit_id: str,
) -> ConnectedBranchPreview:
    """Propose one attached branch, splitting an existing edge at its interior pixel.

    Root attachment must be exact. No nearest-point snap, bridge, or mask
    inference is performed. Split edges preserve their exact original summed
    node-to-node lengths; the new segment contributes length exactly once.
    All edits remain unverified until explicitly reviewed and persisted.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", edit_id):
        raise BranchEditError(
            "Edit ID must contain 1-48 alphanumeric, hyphen or underscore characters"
        )
    path = _checked_path(branch_pixels)
    node_by_id, occupied = _validate_graph(nodes, edges)
    ids = {
        "root": f"manual-{edit_id}-root",
        "tip": f"manual-{edit_id}-tip",
        "upstream": f"manual-{edit_id}-upstream",
        "downstream": f"manual-{edit_id}-downstream",
        "branch": f"manual-{edit_id}-branch",
    }
    all_ids = set(node_by_id) | {edge.id for edge in edges}
    if any(identifier in all_ids for identifier in ids.values()):
        raise BranchEditError("Edit ID collides with an existing graph identifier")
    if any(point in occupied for point in path[1:]):
        raise BranchEditError("Proposed branch overlaps existing segments beyond its attachment")

    original_tle = total_graph_length_pixels(edges)
    if not nodes and not edges:
        root = _new_endpoint(ids["root"], path[0])
        tip = _new_endpoint(ids["tip"], path[-1])
        new_edge = _edge(ids["branch"], root, tip, path)
        return ConnectedBranchPreview(
            nodes=(root, tip),
            edges=(new_edge,),
            attached_node_id=None,
            added_edge_id=new_edge.id,
            superseded_edge_ids=(),
            replacement_edge_ids=(),
            original_total_length_pixels=0.0,
            proposed_total_length_pixels=new_edge.node_to_node_length_pixels,
            added_length_pixels=new_edge.node_to_node_length_pixels,
        )

    root_pixel = path[0]
    matching_nodes = [node for node in nodes if root_pixel in node.source_pixels]
    if len(matching_nodes) > 1:
        raise BranchEditError("Attachment is ambiguous between existing graph nodes")
    root = matching_nodes[0] if matching_nodes else None
    superseded: tuple[str, ...] = ()
    replacements: tuple[str, ...] = ()
    updated_nodes = list(nodes)
    updated_edges = list(edges)

    if root is not None:
        incident_count = sum(
            (edge.source_node_id == root.id) + (edge.target_node_id == root.id) for edge in edges
        )
        root = replace(
            root,
            kind="junction" if incident_count else "endpoint",
            external_connection_count=incident_count + 1,
        )
        updated_nodes = [root if node.id == root.id else node for node in nodes]

    if root is None:
        candidates = [
            (edge, index)
            for edge in edges
            for index in range(1, len(edge.pixels) - 1)
            if edge.pixels[index] == root_pixel
        ]
        if len(candidates) != 1:
            raise BranchEditError(
                "Branch must start at exactly one existing node or an interior segment pixel; "
                "disconnected candidates cannot be approved"
            )
        target_edge, index = candidates[0]
        source = node_by_id[target_edge.source_node_id]
        target = node_by_id[target_edge.target_node_id]
        root = _new_endpoint(ids["root"], root_pixel, kind="junction")
        left = _edge(ids["upstream"], source, root, target_edge.pixels[: index + 1])
        right = _edge(ids["downstream"], root, target, target_edge.pixels[index:])
        if not isclose(
            left.node_to_node_length_pixels + right.node_to_node_length_pixels,
            target_edge.node_to_node_length_pixels,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise BranchEditError("Splitting the segment changed the original measured length")
        updated_nodes.append(root)
        updated_edges = [edge for edge in edges if edge.id != target_edge.id]
        updated_edges.extend([left, right])
        superseded = (target_edge.id,)
        replacements = (left.id, right.id)

    tip = _new_endpoint(ids["tip"], path[-1])
    updated_nodes.append(tip)
    added_edge = _edge(ids["branch"], root, tip, path)
    updated_edges.append(added_edge)
    proposed_tle = total_graph_length_pixels(updated_edges)
    if not isclose(
        proposed_tle,
        original_tle + added_edge.node_to_node_length_pixels,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise BranchEditError("New connected graph must retain original unique-segment length")
    return ConnectedBranchPreview(
        nodes=tuple(updated_nodes),
        edges=tuple(updated_edges),
        attached_node_id=root.id,
        added_edge_id=added_edge.id,
        superseded_edge_ids=superseded,
        replacement_edge_ids=replacements,
        original_total_length_pixels=original_tle,
        proposed_total_length_pixels=proposed_tle,
        added_length_pixels=added_edge.node_to_node_length_pixels,
    )
