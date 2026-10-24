"""Opt-in point-cloud extrema-preserving display and saved-workflow parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project


def _points() -> list[list[float]]:
    points = [[float(index), 0.0, 0.0] for index in range(513)]
    points[511] = [1_000_000.0, -50.0, 7.0]
    return points


def _params() -> dict:
    return {
        "points": _points(),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed field ruler",
        "relative_scale_uncertainty": 0.1,
        "preserve_axis_extrema_in_preview": True,
        "specimen_id": "coral-16",
        "observation_id": "survey:2026-10-24",
        "observed_at_utc": "2026-10-24T10:30:00-05:00",
    }


def test_opt_in_extrema_pinning_keeps_sample_bounded_and_source_indices() -> None:
    params = _params()
    points = params["points"]
    default = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed field ruler",
    )
    pinned = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed field ruler",
        preserve_axis_extrema_in_preview=True,
    )
    assert 511 not in default["preview_point_indices"]
    assert default["preview_omitted_axis_extrema"] == ["x_max", "y_min", "z_max"]
    indices = pinned["preview_point_indices"]
    assert len(indices) == 512
    assert indices == sorted(set(indices))
    assert indices[0] == 0
    assert indices[-1] == 512
    assert 511 in indices
    assert 511 in pinned["preview_extrema_source_indices"]
    assert pinned["preview_sampling_strategy"] == "uniform_index_extrema_preserving"
    assert pinned["preview_axis_extrema_covered"] is True
    assert pinned["preview_omitted_axis_extrema"] == []
    assert "preview_omits_axis_extrema" not in pinned["qc_warnings"]
    assert pinned["preview_points_in_source_frame_m"][indices.index(511)] == pytest.approx(
        [10000.0, -0.5, 0.07]
    )
    assert pinned["axis_aligned_dimensions_m"] == default["axis_aligned_dimensions_m"]
    assert pinned["provenance"]["geometry_sha256"] == default["provenance"]["geometry_sha256"]
    assert pinned["provenance"]["calibration_verified"] is False
    assert pinned["measurement_status"] == "caller_supplied_unverified"
    assert pinned["branch_length_m"] is None
    with pytest.raises(ValueError, match="must be a boolean"):
        measure_point_cloud_preview(
            points=points,
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Unreviewed field ruler",
            preserve_axis_extrema_in_preview="true",  # type: ignore[arg-type]
        )


def test_opt_in_extrema_standalone_and_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "Extrema-aware point cloud")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _params()
    endpoint = f"{base}/spatial/point-cloud-preview"
    standalone = client.post(endpoint, json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    invalid = client.post(endpoint, json={**params, "preserve_axis_extrema_in_preview": "true"})
    assert invalid.status_code == 422, invalid.text
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    node = next(n for n in registry.json() if n["node_type"] == "point_cloud_preview")
    assert node["optional_parameters"]["preserve_axis_extrema_in_preview"] is False
    graph = {
        "graph_id": "point-cloud-extrema-preserving-v14",
        "name": "Review source-frame point cloud extrema",
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
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    payload = artifact["payload_json"]
    for key in (
        "preview_point_indices",
        "preview_extrema_source_indices",
        "preview_sampling_strategy",
        "preview_omitted_axis_extrema",
        "preview_axis_extrema_covered",
        "preview_points_in_source_frame_m",
        "qc_warnings",
        "axis_aligned_dimensions_m",
        "provenance",
        "measurement_status",
    ):
        assert payload[key] == expected[key]
    assert payload["project_id"] == project_id
    assert payload["provenance"]["specimen_identity_verified"] is False
    assert payload["provenance"]["coordinate_registration_verified"] is False
    assert len(artifact["payload_sha256"]) == 64
