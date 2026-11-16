"""Scale-only point preview intervals must agree across direct and persisted workflows."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

POINTS = [[-2.0, 3.0, 0.0], [4.0, -1.0, 1.0], [0.0, 0.0, 0.0]]
PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property float x\nproperty float y\nproperty float z\nend_header\n"
    "-2 3 0\n4 -1 1\n0 0 0\n"
)


@pytest.mark.parametrize("uncertainty", [None, 0.0, 0.2])
def test_signed_preview_intervals_are_scale_only(uncertainty: float | None) -> None:
    result = measure_point_cloud_preview(
        points=POINTS,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified field ruler",
        relative_scale_uncertainty=uncertainty,
    )
    intervals = result["preview_point_scale_intervals_m"]
    if uncertainty is None:
        assert intervals is None
    else:
        assert intervals is not None
        assert len(intervals) == len(result["preview_point_indices"])
        for point, point_intervals in zip(
            result["preview_points_in_source_frame_m"], intervals, strict=True
        ):
            for coordinate, limits in zip(point, point_intervals, strict=True):
                assert limits == pytest.approx(
                    sorted(
                        [
                            coordinate * (1 - uncertainty),
                            coordinate * (1 + uncertainty),
                        ]
                    )
                )
        assert intervals[0][0] == pytest.approx(
            [-0.02 * (1 + uncertainty), -0.02 * (1 - uncertainty)]
        )
        assert intervals[0][2] == [0.0, 0.0]
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_preview_scale_intervals_standalone_and_saved_workflow_parity(
    client: TestClient, source_format: str
) -> None:
    project_id = str(create_project(client, f"Preview scale intervals {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field ruler",
        "relative_scale_uncertainty": 0.2,
        **({"ply_text": PLY} if source_format == "ply" else {"points": POINTS}),
    }
    direct = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert direct.status_code == 200, direct.text
    expected = direct.json()
    assert expected["preview_point_scale_intervals_m"] is not None

    graph = {
        "graph_id": f"point-preview-scale-{source_format}-v14",
        "name": "Calibrated point preview uncertainty",
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
    for key in (
        "preview_point_indices",
        "preview_points_in_source_frame_m",
        "preview_point_scale_intervals_m",
        "provenance",
        "measurement_status",
    ):
        assert artifact[key] == expected[key]
    assert artifact["project_id"] == project_id
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["provenance"]["coordinate_registration_verified"] is False

@pytest.mark.parametrize("source_format", ["xyz", "ply"])
def test_dimension_lower_scale_interval_underflow_is_explicit_and_workflow_safe(
    client: TestClient, source_format: str
) -> None:
    """A positive extent cannot silently acquire a zero lower uncertainty bound."""
    scale = 1e-323
    points = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=scale,
        calibration_method="ruler",
        calibration_evidence="Synthetic numeric boundary; not a verified calibration",
        relative_scale_uncertainty=0.9,
    )
    assert direct["axis_aligned_dimensions_m"] == [scale, 0.0, 0.0]
    assert direct["axis_aligned_dimension_scale_interval_m"] == [
        None,
        [0.0, 0.0],
        [0.0, 0.0],
    ]
    assert "dimension_uncertainty_interval_below_numeric_resolution" in direct["qc_warnings"]
    assert direct["provenance"]["calibration_verified"] is False

    # Physical zero at 100% relative uncertainty is distinct from numeric loss.
    # A still-representable subnormal positive lower bound is also retained.
    for uncertainty, lower_bound in ((1.0, 0.0), (0.5, 5e-324)):
        valid = measure_point_cloud_preview(
            points=points,
            meters_per_unit=scale,
            calibration_method="ruler",
            calibration_evidence="Synthetic interval control; unverified",
            relative_scale_uncertainty=uncertainty,
        )
        assert valid["axis_aligned_dimension_scale_interval_m"][0][0] == lower_bound
        assert valid["axis_aligned_dimension_scale_interval_m"][1:] == [
            [0.0, 0.0],
            [0.0, 0.0],
        ]
        assert (
            "dimension_uncertainty_interval_below_numeric_resolution" not in valid["qc_warnings"]
        )

    project_id = str(create_project(client, f"Dimension lower interval {source_format}")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic numeric boundary; not a verified calibration",
        "relative_scale_uncertainty": 0.9,
    }
    if source_format == "xyz":
        params["points"] = points
    else:
        params["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 2\n"
            "property double x\nproperty double y\nproperty double z\n"
            "end_header\n0 0 0\n1 0 0\n"
        )
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    expected = response.json()
    assert (
        expected["axis_aligned_dimension_scale_interval_m"]
        == direct["axis_aligned_dimension_scale_interval_m"]
    )
    assert expected["qc_warnings"] == direct["qc_warnings"]
    graph = {
        "graph_id": f"dimension-subresolution-{source_format}-v14",
        "name": "Provisional dimension scale uncertainty",
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["payload_json"] == expected
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert artifact["payload_json"]["provenance"]["calibration_verified"] is False
    assert len(artifact["payload_sha256"]) == 64
