"""Standalone and saved Workflow Builder regression for 1.4 point-cloud preview."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import (
    measure_point_cloud_preview,
    parse_ascii_ply_points,
)
from reefvision.tests.test_annotations import create_project

PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property float z\nproperty float x\nproperty float y\nend_header\n"
    "0 0 0\n0 2 0\n0 0 3\n"
)
PARAMS = {
    "ply_text": PLY,
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed ruler",
    "relative_scale_uncertainty": 0.1,
}


def test_ply_parser_and_geometry_uncertainty() -> None:
    points = parse_ascii_ply_points(PLY)
    assert points == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    result = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed ruler",
        relative_scale_uncertainty=0.1,
    )
    assert result["axis_aligned_dimensions_m"] == pytest.approx([0.02, 0.03, 0])
    assert result["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx([0.002, 0.003, 0])
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize(
    "bad",
    [
        PLY.replace("ascii", "binary_little_endian"),
        PLY.replace("element vertex 3", "element vertex 3000"),
        PLY.replace("end_header", "element face 0\nend_header"),
        PLY.replace("0 2 0", "nan 2 0"),
        PLY.replace("0 2 0", "0 2 1e12"),
        PLY.replace("property float y", "property float x"),
    ],
)
def test_bad_ply_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        measure_point_cloud_preview(
            points=parse_ascii_ply_points(bad),
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Unreviewed ruler",
        )


def test_standalone_and_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "Point cloud")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=PARAMS)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["source_format"] == "ply_ascii_point_cloud"
    assert (
        client.post(
            f"{base}/spatial/point-cloud-preview",
            json={**PARAMS, "points": [[0, 0, 0]]},
        ).status_code
        == 422
    )
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    node = next(n for n in registry.json() if n["node_type"] == "point_cloud_preview")
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["point_cloud_measurement_preview"]
    graph = {
        "graph_id": "point-cloud-v14",
        "name": "Point cloud extents",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": PARAMS},
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
    assert saved.json()["graph_json"]["nodes"][1]["parameters"]["ply_text"] == PLY
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
    assert (
        artifact["payload_json"]["axis_aligned_dimensions_m"]
        == expected["axis_aligned_dimensions_m"]
    )
    for key in ("axis_aligned_min_in_source_frame_m", "axis_aligned_max_in_source_frame_m"):
        assert artifact["payload_json"][key] == expected[key]
    assert artifact["payload_json"]["provenance"] == expected["provenance"]
    assert artifact["payload_json"]["surface_area_m2"] is None
    assert artifact["payload_json"]["project_id"] == project_id
    assert len(artifact["payload_sha256"]) == 64


def test_bounds_preserve_negative_source_coordinates() -> None:
    result = measure_point_cloud_preview(
        points=[[-2, -3, -4], [1, 2, 3]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
    )
    assert result["axis_aligned_min_in_source_frame_m"] == pytest.approx([-0.02, -0.03, -0.04])
    assert result["axis_aligned_max_in_source_frame_m"] == pytest.approx([0.01, 0.02, 0.03])
    assert result["axis_aligned_dimensions_m"] == pytest.approx([0.03, 0.05, 0.07])
    assert result["measurement_status"] == "caller_supplied_unverified"
