"""Persisted Workflow Builder parity for mesh measurements and missing uncertainty."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


@pytest.mark.parametrize("relative_scale_uncertainty", [0.05, None])
def test_saved_mesh_patch_areas_match_standalone_preview(
    client: TestClient, relative_scale_uncertainty: float | None
) -> None:
    project_id = str(create_project(client, "Mesh patch areas")["id"])
    params = {
        "vertices": [
            [0, 0, 0],
            [2, 0, 0],
            [0, 3, 0],
            [10, 0, 0],
            [14, 0, 0],
            [10, 5, 0],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed field scale",
        "relative_scale_uncertainty": relative_scale_uncertainty,
    }
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "mesh-patch-areas-v14",
        "name": "Patch areas",
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
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    for key in (
        "edge_connected_patch_face_counts",
        "edge_connected_patch_degenerate_face_counts",
        "edge_connected_patch_boundary_edge_counts",
        "boundary_edge_length_m",
        "boundary_edge_length_scale_interval_m",
        "boundary_edge_length_scale_uncertainty_m",
        "edge_connected_patch_boundary_edge_lengths_m",
        "edge_connected_patch_boundary_length_scale_intervals_m",
        "edge_connected_patch_boundary_length_scale_uncertainties_m",
        "edge_connected_patch_nonmanifold_edge_counts",
        "edge_connected_patch_inconsistent_winding_edge_counts",
        "edge_connected_patch_surface_areas_m2",
        "edge_connected_patch_area_scale_uncertainties_m2",
        "edge_connected_patch_axis_aligned_dimensions_m",
        "edge_connected_patch_dimension_scale_uncertainties_m",
        "area_weighted_surface_centroid_m",
        "area_weighted_centroid_scale_uncertainty_m",
        "edge_connected_patch_area_weighted_surface_centroids_m",
        "edge_connected_patch_centroid_scale_uncertainties_m",
    ):
        expected = standalone.json()[key]
        if expected is None:
            assert artifact[key] is None
        elif isinstance(expected, list) and expected and isinstance(expected[0], list):
            assert len(artifact[key]) == len(expected)
            for actual_row, expected_row in zip(artifact[key], expected, strict=True):
                assert actual_row == pytest.approx(expected_row)
        else:
            assert artifact[key] == pytest.approx(expected)
    assert artifact["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.0003, 0.001])
    assert artifact["edge_connected_patch_boundary_edge_counts"] == [3, 3]
    if relative_scale_uncertainty is None:
        assert artifact["boundary_edge_length_scale_interval_m"] is None
        assert artifact["edge_connected_patch_boundary_length_scale_intervals_m"] is None
        assert artifact["boundary_edge_length_scale_uncertainty_m"] is None
        assert artifact["edge_connected_patch_boundary_length_scale_uncertainties_m"] is None
        assert artifact["edge_connected_patch_area_scale_uncertainties_m2"] is None
        assert artifact["edge_connected_patch_dimension_scale_uncertainties_m"] is None
        assert artifact["area_weighted_centroid_scale_uncertainty_m"] is None
        assert artifact["edge_connected_patch_centroid_scale_uncertainties_m"] is None
    else:
        length = artifact["boundary_edge_length_m"]
        assert artifact["boundary_edge_length_scale_interval_m"] == pytest.approx(
            [length * 0.95, length * 1.05]
        )
        for patch_length, interval in zip(
            artifact["edge_connected_patch_boundary_edge_lengths_m"],
            artifact["edge_connected_patch_boundary_length_scale_intervals_m"],
            strict=True,
        ):
            assert interval == pytest.approx([patch_length * 0.95, patch_length * 1.05])
        assert artifact["boundary_edge_length_scale_uncertainty_m"] > 0
        assert artifact["edge_connected_patch_area_scale_uncertainties_m2"][0] > 0
    assert artifact["boundary_edge_length_m"] == pytest.approx(
        sum(artifact["edge_connected_patch_boundary_edge_lengths_m"])
    )
    assert artifact["edge_connected_patch_degenerate_face_counts"] == [0, 0]
    assert (
        artifact["edge_connected_patch_geometry_sha256"]
        == standalone.json()["edge_connected_patch_geometry_sha256"]
    )
    assert artifact["edge_connected_patch_nonmanifold_edge_counts"] == [0, 0]
    assert artifact["edge_connected_patch_inconsistent_winding_edge_counts"] == [0, 0]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
    assert (
        artifact["provenance"]["geometry_sha256"]
        == (standalone.json()["provenance"]["geometry_sha256"])
    )
