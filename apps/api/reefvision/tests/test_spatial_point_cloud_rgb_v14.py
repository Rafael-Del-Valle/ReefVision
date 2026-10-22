"""1.4 RGB PLY import: validated color is not a scientific measurement."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import parse_ascii_ply_points
from reefvision.tests.test_annotations import create_project

RGB_PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property uchar blue\nproperty float z\nproperty uchar red\n"
    "property float x\nproperty uchar green\nproperty float y\nend_header\n"
    "255 0 0 0 128 0\n0 0 255 2 64 0\n7 0 11 0 22 3\n"
)


def test_rgb_ply_imports_xyz_without_treating_color_as_geometry() -> None:
    assert parse_ascii_ply_points(RGB_PLY) == [
        [0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
        [0.0, 3.0, 0.0],
    ]


@pytest.mark.parametrize(
    "bad",
    [
        RGB_PLY.replace("property uchar red", "property float red"),
        RGB_PLY.replace("property uchar green\n", ""),
        RGB_PLY.replace("255 0 0 0 128 0", "256 0 0 0 128 0"),
        RGB_PLY.replace("255 0 0 0 128 0", "-1 0 0 0 128 0"),
        RGB_PLY.replace("255 0 0 0 128 0", "2.5 0 0 0 128 0"),
        RGB_PLY.replace("255 0 0 0 128 0", "255 nan 0 0 128 0"),
    ],
)
def test_bad_rgb_ply_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_ascii_ply_points(bad)


def test_rgb_ply_standalone_and_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "RGB point cloud preview")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "ply_text": RGB_PLY,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified reference",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1]],
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["measurement_status"] == "caller_supplied_unverified"
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["surface_area_m2"] is None
    graph = {
        "graph_id": "point-cloud-rgb-v14",
        "name": "RGB point cloud geometry preview",
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
        "axis_aligned_dimensions_m",
        "selected_point_chords",
        "arithmetic_centroid_in_source_frame_m",
        "provenance",
    ):
        assert payload[key] == expected[key]
    assert payload["project_id"] == project_id
    assert len(artifact["payload_sha256"]) == 64
