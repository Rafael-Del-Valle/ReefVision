"""GLB saved graph execution smoke test."""

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


def test_saved_glb(client: TestClient) -> None:
    pid = create_project(client, "GLB saved")["id"]
    params = {
        "glb_base64": make_glb(),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Pending review",
    }
    graph = {
        "graph_id": "glb-v14",
        "name": "GLB",
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
    base = f"/api/v1/projects/{pid}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = detail.json()["artifacts"]
    assert any(
        a["payload_json"]["provenance"]["source_format"] == "glb_2_0"
        for a in artifacts
        if a["data_type"] == "mesh_measurement_preview"
    )
