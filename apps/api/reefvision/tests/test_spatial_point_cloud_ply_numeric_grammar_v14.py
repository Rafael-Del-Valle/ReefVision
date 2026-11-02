"""ASCII PLY numeric grammar and lossless-zero safeguards for spatial science."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import parse_ascii_ply_points
from reefvision.tests.test_annotations import create_project

PLY = (
    "ply\nformat ascii 1.0\nelement vertex 2\n"
    "property float x\nproperty float y\nproperty float z\n"
    "end_header\n0 0 0\n1 2 3\n"
)
PARAMS = {
    "ply_text": PLY,
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified survey ruler",
    "relative_scale_uncertainty": 0.1,
}


@pytest.mark.parametrize(
    "invalid",
    [
        PLY.replace("element vertex 2", "element vertex 0_2"),
        PLY.replace("element vertex 2", "element vertex +2"),
        PLY.replace("1 2 3", "1_0 2 3"),
        PLY.replace("1 2 3", "1e3_0 2 3"),
        PLY.replace("1 2 3", "1e-9999 2 3"),
        PLY.replace("1 2 3", "1e9999 2 3"),
    ],
)
def test_non_ply_numbers_never_enter_geometry(invalid: str) -> None:
    with pytest.raises(ValueError):
        parse_ascii_ply_points(invalid)


def test_standard_decimal_exponent_and_exact_zero_remain_supported() -> None:
    valid = PLY.replace("element vertex 2", "element vertex 002").replace(
        "1 2 3", "+1. .25 1e-2"
    ).replace("0 0 0", "-0.0 0.00e-9999 0")
    assert parse_ascii_ply_points(valid) == [
        [-0.0, 0.0, 0.0],
        [1.0, 0.25, 0.01],
    ]


def test_invalid_late_coordinate_does_not_mutate_caller_colors() -> None:
    colored = PLY.replace(
        "property float z\n",
        "property float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n",
    ).replace("0 0 0\n1 2 3\n", "0 0 0 1 2 3\n1e-9999 2 3 4 5 6\n")
    existing = [[7, 8, 9]]
    with pytest.raises(ValueError, match="underflows"):
        parse_ascii_ply_points(colored, colors_out=existing)
    assert existing == [[7, 8, 9]]


@pytest.mark.parametrize(
    "invalid",
    [
        PLY.replace("element vertex 2", "element vertex 0_2"),
        PLY.replace("1 2 3", "1_0 2 3"),
        PLY.replace("1 2 3", "1e-9999 2 3"),
    ],
)
def test_standalone_and_saved_graph_reject_invalid_ply_without_artifact(
    client: TestClient, invalid: str
) -> None:
    project_id = str(create_project(client, "PLY numeric integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {**PARAMS, "ply_text": invalid}
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 422, standalone.text

    graph = {
        "graph_id": "ply-numeric-integrity-v14",
        "name": "Reject invalid imported point coordinates",
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
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "point_cloud_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_valid_ply_standalone_and_persisted_graph_replay_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "PLY decimal exponent replay")["id"])
    base = f"/api/v1/projects/{project_id}"
    valid = PLY.replace("1 2 3", "+1. .25 1e-2")
    params = {**PARAMS, "ply_text": valid}
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["axis_aligned_dimensions_m"] == pytest.approx([0.01, 0.0025, 0.0001])
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "ply-valid-numeric-v14",
        "name": "Reproduce valid point-cloud numeric preview",
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
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["payload_json"] == expected
    assert artifact["payload_json"]["surface_area_m2"] is None
    assert artifact["payload_json"]["branch_length_m"] is None
