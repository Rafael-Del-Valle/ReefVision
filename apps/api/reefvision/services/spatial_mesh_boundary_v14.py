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
