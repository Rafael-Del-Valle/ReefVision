"""Validate synthetic Track C centerline references without third-party dependencies.

Run from repository root:
    python docs/research/fixtures/validate_centerline_reference_v14.py

This validates the *reference data*, not an anatomical measurement implementation.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

REFERENCE = Path(__file__).with_name("centerline_reference_v14.json")


def validate_reference(path: Path = REFERENCE) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == "reefvision.track_c.centerline_reference.v1"
    assert data["status"] == "synthetic_reference_only_not_anatomical_validation"
    scale = data["calibration"]["meters_per_unit"]
    bound = data["calibration"]["absolute_scale_bound_meters_per_unit"]
    assert math.isfinite(scale) and scale > 0
    assert math.isfinite(bound) and 0 <= bound < scale
    seen: set[str] = set()
    for case in data["cases"]:
        name = case["id"]
        assert name not in seen, f"duplicate case: {name}"
        seen.add(name)
        nodes = {row[0]: tuple(row[1:]) for row in case["nodes"]}
        assert len(nodes) == len(case["nodes"]), f"duplicate node in {name}"
        assert all(len(p) == 3 and all(math.isfinite(x) for x in p) for p in nodes.values())
        assert nodes, f"empty centerline graph in {name}"
        edges: set[tuple[str, str]] = set()
        adjacency: dict[str, set[str]] = defaultdict(set)
        total = 0.0
        for a, b in case["edges"]:
            assert a in nodes and b in nodes and a != b, name
            key = tuple(sorted((a, b)))
            assert key not in edges, f"duplicate undirected edge in {name}"
            assert math.dist(nodes[a], nodes[b]) > 0, f"zero-length edge in {name}"
            edges.add(key)
            adjacency[a].add(b)
            adjacency[b].add(a)
            total += math.dist(nodes[a], nodes[b])
        assert all(adjacency[node] for node in nodes), f"isolated node in {name}"
        expected = case["expected"]
        for key, observed in (
            ("unique_edge_total_raw", total),
            ("observed_length_m", total * scale),
            ("scale_only_bound_m", total * bound),
        ):
            assert math.isclose(observed, expected[key], rel_tol=1e-10, abs_tol=1e-12), (name, key)
        # A forest has |E| = |V| - components; loops must remain unresolved.
        remaining = set(nodes)
        components = 0
        while remaining:
            components += 1
            frontier = [remaining.pop()]
            while frontier:
                for neighbor in adjacency[frontier.pop()] & remaining:
                    remaining.remove(neighbor)
                    frontier.append(neighbor)
        has_cycle = len(edges) > len(nodes) - components
        has_gap = "missing_edge" in case
        # Disconnected geometry is not a complete observed centerline unless an
        # explicit missing-edge/occlusion annotation explains the gap.
        assert components == 1 or has_gap, f"unreviewed disconnected graph in {name}"
        if has_gap:
            a, b = case["missing_edge"]
            assert a in nodes and b in nodes and a != b, name
            assert tuple(sorted((a, b))) not in edges, name
            # A declared missing edge must explain a disconnected reconstruction,
            # not excuse an unrelated disconnected island.
            assert components == 2, f"one missing edge cannot explain {components} components in {name}"
            reachable = {a}
            frontier = [a]
            while frontier:
                for neighbor in adjacency[frontier.pop()] - reachable:
                    reachable.add(neighbor)
                    frontier.append(neighbor)
            assert b not in reachable, f"gap endpoints already connected in {name}"
        assert expected["unresolved"] == (has_cycle or has_gap), name
        if "branch_count" in expected:
            assert not has_cycle and not has_gap and components == 1, name
            # Count maximal chains, not degree-two sampling vertices.
            branch_count = sum(len(adjacency[n]) for n in nodes if len(adjacency[n]) != 2) // 2
            assert branch_count == expected["branch_count"], name
    assert seen == {
        "straight", "y_shared_trunk", "degree_two_node",
        "loop_requires_review", "occluded_unresolved",
    }
    return sorted(seen)


if __name__ == "__main__":
    validated = validate_reference()
    print(f"Validated {len(validated)} synthetic centerline reference cases: {', '.join(validated)}")
