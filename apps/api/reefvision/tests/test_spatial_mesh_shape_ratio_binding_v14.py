"""Reject contradictory stored morphology summaries; retain workflow parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project


def _mesh(observation: str, date: str, height: int) -> dict:
    return {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, height, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unreviewed field scale",
        "specimen_id": "colony-1",
        "observation_id": observation,
        "observed_at_utc": date,
    }


@pytest.mark.parametrize("tampered_ratio", [0.0, 0.8])
def test_longitudinal_rejects_forged_shape_ratio(tampered_ratio: float) -> None:
    before = preview_from_request(
        MeshPreviewRequest.model_validate(_mesh("early", "2026-10-01T12:00:00Z", 1))
    )
    after = preview_from_request(
        MeshPreviewRequest.model_validate(_mesh("late", "2026-10-02T12:00:00Z", 2))
    )
    before["project_id"] = after["project_id"] = "morphology-study"
    after["surface_area_to_bounding_diagonal_squared_ratio"] = tampered_ratio
    with pytest.raises(
        ValueError, match="Mesh shape ratio contradicts calibrated area and extent"
    ):
        compare_mesh_observations(before, after)


def test_shape_ratio_binding_standalone_and_saved_graph(client: TestClient) -> None:
    project_id = str(create_project(client, "Shape ratio binding")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _mesh("early", "2026-10-01T12:00:00Z", 1)
    after = _mesh("late", "2026-10-02T12:00:00Z", 2)
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["before_surface_area_to_bounding_diagonal_squared_ratio"] == (
        pytest.approx(0.25)
    )
    assert expected["after_surface_area_to_bounding_diagonal_squared_ratio"] == (
        pytest.approx(0.2)
    )
    assert expected["delta_surface_area_to_bounding_diagonal_squared_ratio"] == (
        pytest.approx(-0.05)
    )

    graph = {
        "graph_id": "shape-ratio-binding-v14",
        "name": "Replayed morphology summaries",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "early",
                "node_type": "mesh_surface_preview",
                "parameters": before,
            },
            {
                "node_id": "late",
                "node_type": "mesh_surface_preview",
                "parameters": after,
            },
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": "project-early",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "early",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-late",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "late",
                "target_port_id": "project",
            },
            {
                "edge_id": "early-compare",
                "source_node_id": "early",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "before",
            },
            {
                "edge_id": "late-compare",
                "source_node_id": "late",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "after",
            },
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(
        f"{base}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run.json()["job_id"]),
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["delta_surface_area_to_bounding_diagonal_squared_ratio"] == (
        pytest.approx(-0.05)
    )
    assert artifact["before_surface_area_to_bounding_diagonal_squared_ratio"] == (
        pytest.approx(0.25)
    )
    assert artifact["after_surface_area_to_bounding_diagonal_squared_ratio"] == (
        pytest.approx(0.2)
    )
    assert artifact["measurement_status"] == expected["measurement_status"]
    assert artifact["provenance"]["specimen_identity_verified"] is False
    assert (
        "mesh_shape_ratio_change_is_orientation_sensitive_reconstruction_qc"
        in artifact["qc_warnings"]
    )
