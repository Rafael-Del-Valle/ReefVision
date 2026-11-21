"""Boundary-loop QC parity through direct, API, and persisted workflow paths."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_boundary_v14 import (
    boundary_component_counts,
    boundary_component_lengths,
)
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


def test_boundary_graph_classifies_cycles_without_inventing_holes() -> None:
    assert boundary_component_counts([]) == (0, 0)
    assert boundary_component_counts([(0, 1), (1, 2), (2, 0)]) == (1, 0)
    assert boundary_component_counts([(0, 1), (1, 2)]) == (0, 1)
    assert boundary_component_counts([(0, 1), (1, 2), (2, 0), (0, 3)]) == (0, 1)


def test_boundary_component_lengths_are_separate_and_order_independent() -> None:
    points = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (3.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
    ]
    edges = [(0, 1), (1, 2), (2, 0), (3, 4)]
    cycles, noncycles = boundary_component_lengths(edges, points)
    assert cycles == pytest.approx([2 + 2**0.5])
    assert noncycles == pytest.approx([1.0])
    assert boundary_component_lengths(list(reversed(edges)), points) == (
        cycles,
        noncycles,
    )
    assert boundary_component_lengths([], points) == ([], [])


@pytest.mark.parametrize(
    ("case", "vertices", "faces", "loops", "noncycles", "patch_loops"),
    [
        (
            "closed-tetra",
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
            [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
            0,
            0,
            [0],
        ),
        (
            "open-square",
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            [[0, 1, 2], [0, 2, 3]],
            1,
            0,
            [1],
        ),
        (
            "pinched-boundary",
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]],
            [[0, 1, 2], [1, 0, 3], [0, 1, 4]],
            0,
            1,
            [0],
        ),
        (
            "disconnected-triangles",
            [
                [0, 0, 0],
                [1, 0, 0],
                [0, 1, 0],
                [10, 0, 0],
                [11, 0, 0],
                [10, 1, 0],
            ],
            [[0, 1, 2], [3, 4, 5]],
            2,
            0,
            [1, 1],
        ),
    ],
)
def test_boundary_components_standalone_and_saved_workflow(
    client: TestClient,
    case: str,
    vertices: list[list[int]],
    faces: list[list[int]],
    loops: int,
    noncycles: int,
    patch_loops: list[int],
) -> None:
    params = {
        "vertices": vertices,
        "faces": faces,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed scale awaiting human verification",
        "relative_scale_uncertainty": 0.1,
    }
    direct = measure_mesh_preview(**params)
    keys = (
        "boundary_loop_count",
        "noncycle_boundary_component_count",
        "edge_connected_patch_boundary_loop_counts",
        "edge_connected_patch_noncycle_boundary_component_counts",
        "boundary_loop_perimeters_m",
        "noncycle_boundary_component_lengths_m",
        "edge_connected_patch_boundary_loop_perimeters_m",
        "edge_connected_patch_noncycle_boundary_component_lengths_m",
        "boundary_loop_perimeter_scale_intervals_m",
        "noncycle_boundary_component_length_scale_intervals_m",
        "edge_connected_patch_boundary_loop_perimeter_scale_intervals_m",
        "edge_connected_patch_noncycle_boundary_component_length_scale_intervals_m",
        "qc_warnings",
    )
    assert direct["boundary_loop_count"] == loops
    assert direct["noncycle_boundary_component_count"] == noncycles
    assert direct["edge_connected_patch_boundary_loop_counts"] == patch_loops
    assert direct["edge_connected_patch_noncycle_boundary_component_counts"] == [
        noncycles if case == "pinched-boundary" else 0 for _ in patch_loops
    ]
    assert ("noncycle_mesh_boundary_components" in direct["qc_warnings"]) == bool(noncycles)
    assert len(direct["boundary_loop_perimeters_m"]) == loops
    assert len(direct["noncycle_boundary_component_lengths_m"]) == noncycles
    for length, interval in zip(
        direct["boundary_loop_perimeters_m"],
        direct["boundary_loop_perimeter_scale_intervals_m"],
        strict=True,
    ):
        assert interval == pytest.approx([length * 0.9, length * 1.1])
    for length, interval in zip(
        direct["noncycle_boundary_component_lengths_m"],
        direct["noncycle_boundary_component_length_scale_intervals_m"],
        strict=True,
    ):
        assert interval == pytest.approx([length * 0.9, length * 1.1])
    assert sum(direct["boundary_loop_perimeters_m"]) + sum(
        direct["noncycle_boundary_component_lengths_m"]
    ) == pytest.approx(direct["boundary_edge_length_m"])
    if case == "open-square":
        assert direct["boundary_loop_perimeters_m"] == pytest.approx([0.04])
    if case == "disconnected-triangles":
        assert direct["boundary_loop_perimeters_m"] == pytest.approx([0.01 * (2 + 2**0.5)] * 2)
    if case == "closed-tetra":
        assert direct["boundary_loop_perimeters_m"] == []
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, f"Boundary topology {case}")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": f"boundary-components-{case}-v14",
        "name": "Boundary components",
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
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    for key in keys:
        assert artifact[key] == standalone.json()[key] == direct[key]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False


def test_boundary_component_uncertainty_requires_explicit_scale_range() -> None:
    params = {
        "vertices": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        "faces": [[0, 1, 2], [0, 2, 3]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed field ruler",
    }
    result = measure_mesh_preview(**params)
    assert result["boundary_loop_perimeters_m"] == pytest.approx([0.04])
    assert result["boundary_loop_perimeter_scale_intervals_m"] is None
    assert result["noncycle_boundary_component_length_scale_intervals_m"] is None
    assert result["edge_connected_patch_boundary_loop_perimeter_scale_intervals_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False

    result = measure_mesh_preview(**params, relative_scale_uncertainty=0.0)
    assert result["boundary_loop_perimeter_scale_intervals_m"] == [[0.04, 0.04]]
    assert result["edge_connected_patch_boundary_loop_perimeter_scale_intervals_m"] == [
        [[0.04, 0.04]]
    ]
