"""Exact scale-only mesh area intervals, including saved workflow parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

PARAMETERS = {
    "vertices": [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [10, 0, 0],
        [11, 0, 0],
        [10, 1, 0],
    ],
    "faces": [[0, 1, 2], [3, 4, 5]],
    "meters_per_unit": 0.1,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed scale bar",
    "relative_scale_uncertainty": 0.1,
}


def test_area_intervals_use_squared_scale_bounds_per_patch() -> None:
    result = measure_mesh_preview(**PARAMETERS)
    assert result["surface_area_m2"] == pytest.approx(0.01)
    assert result["surface_area_scale_interval_m2"] == pytest.approx([0.0081, 0.0121])
    for interval in result["edge_connected_patch_area_scale_intervals_m2"]:
        assert interval == pytest.approx([0.00405, 0.00605])
    # Existing linearized sensitivity is retained for compatibility, but it
    # is not an exact lower/upper interval and is not a confidence interval.
    assert result["area_scale_uncertainty_m2"] == pytest.approx(0.002)
    for interval, expected in zip(
        result["axis_aligned_dimension_scale_intervals_m"],
        ([0.99, 1.21], [0.09, 0.11], [0.0, 0.0]),
        strict=True,
    ):
        assert interval == pytest.approx(expected)
    for intervals in result["edge_connected_patch_dimension_scale_intervals_m"]:
        for interval, expected in zip(
            intervals,
            ([0.09, 0.11], [0.09, 0.11], [0.0, 0.0]),
            strict=True,
        ):
            assert interval == pytest.approx(expected)
    diagonal = result["axis_aligned_bounding_box_diagonal_m"]
    assert result["axis_aligned_bounding_box_diagonal_scale_interval_m"] == pytest.approx(
        [diagonal * 0.9, diagonal * 1.1]
    )
    for diagonal, interval in zip(
        result["edge_connected_patch_bounding_box_diagonals_m"],
        result["edge_connected_patch_bounding_box_diagonal_scale_intervals_m"],
        strict=True,
    ):
        assert interval == pytest.approx([diagonal * 0.9, diagonal * 1.1])
    assert result["confidence_interval"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [None, 0.0, 1.0])
def test_area_interval_missing_zero_and_full_scale_uncertainty(
    uncertainty: float | None,
) -> None:
    result = measure_mesh_preview(**{**PARAMETERS, "relative_scale_uncertainty": uncertainty})
    if uncertainty is None:
        assert result["surface_area_scale_interval_m2"] is None
        assert result["edge_connected_patch_area_scale_intervals_m2"] is None
        assert result["axis_aligned_dimension_scale_intervals_m"] is None
        assert result["axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
        assert result["edge_connected_patch_dimension_scale_intervals_m"] is None
        assert result["edge_connected_patch_bounding_box_diagonal_scale_intervals_m"] is None
    else:
        lower = 0.01 * (1 - uncertainty) ** 2
        upper = 0.01 * (1 + uncertainty) ** 2
        assert result["surface_area_scale_interval_m2"] == pytest.approx([lower, upper])
        for interval in result["edge_connected_patch_area_scale_intervals_m2"]:
            assert interval == pytest.approx([lower / 2, upper / 2])
        for dimension, interval in zip(
            result["axis_aligned_dimensions_m"],
            result["axis_aligned_dimension_scale_intervals_m"],
            strict=True,
        ):
            assert interval == pytest.approx(
                [dimension * (1 - uncertainty), dimension * (1 + uncertainty)]
            )


def test_area_scale_intervals_survive_saved_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh area scale interval")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=PARAMETERS)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["surface_area_scale_interval_m2"] == pytest.approx([0.0081, 0.0121])

    graph = {
        "graph_id": "mesh-area-scale-intervals-v14",
        "name": "Unverified scale-only surface intervals",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": PARAMETERS,
            },
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
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
    assert artifact["surface_area_scale_interval_m2"] == expected["surface_area_scale_interval_m2"]
    assert (
        artifact["edge_connected_patch_area_scale_intervals_m2"]
        == expected["edge_connected_patch_area_scale_intervals_m2"]
    )
    assert artifact["provenance"]["geometry_sha256"] == expected["provenance"]["geometry_sha256"]
    for key in (
        "axis_aligned_dimension_scale_intervals_m",
        "axis_aligned_bounding_box_diagonal_scale_interval_m",
        "edge_connected_patch_dimension_scale_intervals_m",
        "edge_connected_patch_bounding_box_diagonal_scale_intervals_m",
    ):
        assert artifact[key] == expected[key]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
