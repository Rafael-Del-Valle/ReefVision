"""Point-cloud envelope uncertainty and saved-graph parity for 1.4."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project


def test_calibrated_envelope_and_scale_interval() -> None:
    result = measure_point_cloud_preview(
        points=[[0, 0, 0], [2, 3, 4]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
        relative_scale_uncertainty=0.1,
    )
    volume = 0.02 * 0.03 * 0.04
    assert result["axis_aligned_bounding_box_envelope_volume_m3"] == pytest.approx(volume)
    interval = result["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
    assert interval == pytest.approx([volume * 0.9**3, volume * 1.1**3])
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize("uncertainty", [None, 0.0, 0.1, 1.0])
def test_degenerate_cloud_envelope(uncertainty: float | None) -> None:
    result = measure_point_cloud_preview(
        points=[[0, 0, 0], [2, 3, 0]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
        relative_scale_uncertainty=uncertainty,
    )
    assert result["axis_aligned_bounding_box_envelope_volume_m3"] == 0
    interval = result["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
    if uncertainty is None:
        assert interval is None
    else:
        assert interval == [0, 0]


def test_envelope_saved_workflow_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "Envelope preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "points": [[0, 0, 0], [2, 3, 4]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler",
        "relative_scale_uncertainty": 0.1,
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    graph = {
        "graph_id": "point-cloud-envelope-v14",
        "name": "Point cloud envelope",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": params,
            },
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
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    payload = artifact["payload_json"]
    assert (
        payload["axis_aligned_bounding_box_envelope_volume_m3"]
        == (expected["axis_aligned_bounding_box_envelope_volume_m3"])
    )
    assert (
        payload["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"]
        == (expected["axis_aligned_bounding_box_envelope_volume_scale_interval_m3"])
    )
    assert payload["provenance"] == expected["provenance"]
    assert payload["project_id"] == project_id
    assert payload["measurement_status"] == "caller_supplied_unverified"
