"""Combinatorial boundary components of bounded triangle meshes.

A closed boundary-edge cycle is a mesh-topology observation, not evidence
that an opening represents a biological hole or that a scan is complete.
"""

from __future__ import annotations


def boundary_component_counts(edges: list[tuple[int, int]]) -> tuple[int, int]:
    """Count simple boundary cycles and noncycle components by vertex index.

    Input edges must be unique undirected boundary edges (incidence exactly
    one). A connected boundary graph is a cycle only when every vertex has
    degree two. Branching/pinched/open chains are counted separately rather
    than incorrectly reported as complete boundary loops.
    """
    adjacency: dict[int, set[int]] = {}
    for first, second in edges:
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)

    visited: set[int] = set()
    loops = 0
    noncycle_components = 0
    for start in sorted(adjacency):
        if start in visited:
            continue
        stack = [start]
        component: list[int] = []
        while stack:
            vertex = stack.pop()
            if vertex in visited:
                continue
            visited.add(vertex)
            component.append(vertex)
            stack.extend(adjacency[vertex] - visited)
        if all(len(adjacency[vertex]) == 2 for vertex in component):
            loops += 1
        else:
            noncycle_components += 1
    return loops, noncycle_components


def boundary_component_lengths(
    edges: list[tuple[int, int]],
    points: list[tuple[float, float, float]],
) -> tuple[list[float], list[float]]:
    """Return lengths of cyclic and noncyclic boundary components in source units.

    Components are ordered by their lowest source vertex index. The input
    contains unique, undirected edges with exactly one incident triangle.
    These are mesh boundaries, not verified anatomical openings.
    """
    from math import dist, fsum

    adjacency: dict[int, set[int]] = {}
    for first, second in edges:
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)

    owner: dict[int, int] = {}
    is_cycle: list[bool] = []
    for start in sorted(adjacency):
        if start in owner:
            continue
        component_index = len(is_cycle)
        stack = [start]
        component_vertices: list[int] = []
        while stack:
            vertex = stack.pop()
            if vertex in owner:
                continue
            owner[vertex] = component_index
            component_vertices.append(vertex)
            stack.extend(adjacency[vertex] - owner.keys())
        is_cycle.append(all(len(adjacency[vertex]) == 2 for vertex in component_vertices))

    component_lengths: list[list[float]] = [[] for _ in is_cycle]
    for first, second in edges:
        component_lengths[owner[first]].append(dist(points[first], points[second]))

    cycle_lengths = [
        fsum(lengths) for cycle, lengths in zip(is_cycle, component_lengths, strict=True) if cycle
    ]
    noncycle_lengths = [
        fsum(lengths)
        for cycle, lengths in zip(is_cycle, component_lengths, strict=True)
        if not cycle
    ]
    return cycle_lengths, noncycle_lengths
