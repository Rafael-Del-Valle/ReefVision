"""Quantized point-cloud scale intervals remain unresolved in saved workflows."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

POINTS = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property double x\nproperty double y\nproperty double z\n"
    "end_header\n0 0 0\n1 0 0\n2 0 0\n"
)
WARNINGS = {
    "selected_chord_uncertainty_interval_below_numeric_resolution",
    "dimension_uncertainty_interval_below_numeric_resolution",
    "coordinate_uncertainty_interval_below_numeric_resolution",
}


def measure(scale: float, uncertainty: float) -> dict[str, Any]:
    return measure_point_cloud_preview(
        points=POINTS,
        meters_per_unit=scale,
        calibration_method="ruler",
        calibration_evidence="Synthetic floating-point example; unverified",
        relative_scale_uncertainty=uncertainty,
        point_index_pairs=[[0, 1]],
    )


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_quantized_scale_science_matches_saved_workflow(
    client: TestClient, source_format: str
) -> None:
    direct = measure(5e-324, 0.1)
    assert direct["selected_point_chords"][0]["chord_distance_m"] == 5e-324
    assert direct["selected_point_chords"][0]["chord_distance_scale_interval_m"] is None
    assert direct["axis_aligned_dimensions_m"][0] == 1e-323
    assert direct["axis_aligned_dimension_scale_interval_m"][0] is None
    assert direct["preview_point_scale_intervals_m"][1][0] is None
    assert direct["axis_aligned_max_in_source_frame_scale_interval_m"][0] is None
    assert direct["arithmetic_centroid_in_source_frame_scale_interval_m"][0] is None
    assert WARNINGS.issubset(set(direct["qc_warnings"]))
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, f"Quantized point scales {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    params: dict[str, Any] = {
        "meters_per_unit": 5e-324,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic floating-point example; unverified",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1]],
    }
    if source_format == "xyz":
        params["points"] = POINTS
    else:
        params["ply_text"] = PLY
    direct_response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert direct_response.status_code == 200, direct_response.text
    expected = direct_response.json()
    for key in (
        "selected_point_chords",
        "axis_aligned_dimensions_m",
        "axis_aligned_dimension_scale_interval_m",
        "preview_point_scale_intervals_m",
        "axis_aligned_max_in_source_frame_scale_interval_m",
        "arithmetic_centroid_in_source_frame_scale_interval_m",
        "qc_warnings",
    ):
        assert expected[key] == direct[key]

    graph = {
        "graph_id": f"quantized-point-scale-{source_format}-v14",
        "name": "Quantized point-cloud uncertainty review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
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
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    for key, value in expected.items():
        assert artifact[key] == value
    assert artifact["project_id"] == project_id
    assert artifact["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [0.0, 1.0])
def test_true_zero_and_exact_scale_limits_stay_valid(uncertainty: float) -> None:
    result = measure(5e-324, uncertainty)
    assert WARNINGS.isdisjoint(set(result["qc_warnings"]))
    chord = result["selected_point_chords"][0]["chord_distance_scale_interval_m"]
    assert chord is not None
    assert result["axis_aligned_dimension_scale_interval_m"][0] is not None
    assert result["preview_point_scale_intervals_m"][1][0] is not None
    assert chord == ([5e-324, 5e-324] if uncertainty == 0.0 else [0.0, 1e-323])


def test_normal_size_with_tiny_nonzero_uncertainty_is_not_exact() -> None:
    result = measure(1.0, 1e-20)
    assert result["axis_aligned_dimensions_m"] == [2.0, 0.0, 0.0]
    assert result["axis_aligned_dimension_scale_interval_m"][0] is None
    assert result["selected_point_chords"][0]["chord_distance_scale_interval_m"] is None
    assert result["preview_point_scale_intervals_m"][1][0] is None
    assert WARNINGS.issubset(set(result["qc_warnings"]))
