"""Calibration underflow must not turn positive coral mesh area into zero."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


def mesh_params(scale: float) -> dict:
    return {
        "vertices": [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified physical ruler",
        "relative_scale_uncertainty": 0.05,
    }


def saved_mesh_result(client: TestClient, base: str, params: dict) -> dict:
    graph = {
        "graph_id": "mesh-area-calibration-underflow-v14",
        "name": "Calibrated surface area precision",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": params,
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
    process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


@pytest.mark.parametrize("scale", [1e-180, 1e-200])
def test_positive_source_area_cannot_underflow_to_zero_in_api_or_saved_graph(
    client: TestClient, scale: float
) -> None:
    params = mesh_params(scale)
    with pytest.raises(ValueError, match="Calibrated mesh surface area underflowed to zero"):
        measure_mesh_preview(**params)
    project_id = str(create_project(client, "Mesh area underflow rejection")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "Calibrated mesh surface area underflowed to zero" in response.text

    detail = saved_mesh_result(client, base, params)
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


def test_representable_small_calibration_preserves_standalone_workflow_parity(
    client: TestClient,
) -> None:
    params = mesh_params(1e-6)
    project_id = str(create_project(client, "Representable small mesh area")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["surface_area_m2"] == pytest.approx(3e-12)
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False

    detail = saved_mesh_result(client, base, params)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["surface_area_m2"] == standalone["surface_area_m2"]
    assert (
        artifact["surface_area_scale_interval_m2"] == (standalone["surface_area_scale_interval_m2"])
    )
    assert artifact["provenance"] == standalone["provenance"]


def test_positive_small_patch_cannot_disappear_in_calibrated_area(
    client: TestClient,
) -> None:
    # Total area remains representable, but the second disconnected patch
    # would otherwise be serialized as zero despite positive source area.
    params = {
        **mesh_params(1e-100),
        "vertices": [
            [10.0, 0.0, 0.0],
            [12.0, 0.0, 0.0],
            [10.0, 3.0, 0.0],
            [0.0, 0.0, 0.0],
            [1e-100, 0.0, 0.0],
            [0.0, 1e-100, 0.0],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
    }
    with pytest.raises(ValueError, match="Calibrated mesh patch surface area underflowed to zero"):
        measure_mesh_preview(**params)
    project_id = str(create_project(client, "Patch area underflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "Calibrated mesh patch surface area underflowed to zero" in response.text
    detail = saved_mesh_result(client, base, params)
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


def test_genuinely_degenerate_patch_remains_zero_area() -> None:
    params = {
        **mesh_params(0.1),
        "vertices": [
            [10.0, 0.0, 0.0],
            [12.0, 0.0, 0.0],
            [10.0, 3.0, 0.0],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
    }
    result = measure_mesh_preview(**params)
    assert result["surface_area_m2"] == pytest.approx(0.03)
    assert result["edge_connected_patch_surface_areas_m2"] == pytest.approx([0.03, 0.0])
    assert result["degenerate_face_count"] == 1


def test_representable_small_patch_survives_standalone_and_saved_graph(
    client: TestClient,
) -> None:
    params = {
        **mesh_params(1e-30),
        "vertices": [
            [10.0, 0.0, 0.0],
            [12.0, 0.0, 0.0],
            [10.0, 3.0, 0.0],
            [0.0, 0.0, 0.0],
            [1e-50, 0.0, 0.0],
            [0.0, 1e-50, 0.0],
        ],
        "faces": [[0, 1, 2], [3, 4, 5]],
    }
    project_id = str(create_project(client, "Representable small patch")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    areas = standalone["edge_connected_patch_surface_areas_m2"]
    assert areas[0] == pytest.approx(3e-60)
    assert areas[1] > 0
    assert areas[1] == pytest.approx(5e-161)

    detail = saved_mesh_result(client, base, params)
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["edge_connected_patch_surface_areas_m2"] == areas
    assert artifact["surface_area_scale_interval_m2"] == (
        standalone["surface_area_scale_interval_m2"]
    )
    assert artifact["provenance"] == standalone["provenance"]
