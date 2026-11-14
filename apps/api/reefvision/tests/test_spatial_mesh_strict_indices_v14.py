"""Strict mesh vertex identifiers must survive standalone and saved graph paths."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.tests.test_annotations import create_project

PARAMS = {
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    "faces": [[0, 1, 2]],
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed scale",
    "surface_path_vertex_pairs": [[0, 1]],
}


@pytest.mark.parametrize("invalid", [True, 1.0, "1"])
@pytest.mark.parametrize("field", ["faces", "surface_path_vertex_pairs"])
def test_noninteger_mesh_indices_rejected_by_schema_and_api(
    client: TestClient, field: str, invalid: object
) -> None:
    params = {**PARAMS, field: [[0, invalid, 2]] if field == "faces" else [[0, invalid]]}
    with pytest.raises(PydanticValidationError):
        MeshPreviewRequest.model_validate(params)
    project_id = create_project(client, "Strict mesh indices")["id"]
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 422, response.text


def test_integer_mesh_indices_execute_in_persisted_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Strict mesh workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "strict-mesh-indices-v14",
        "name": "Exact mesh vertex identifiers",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": PARAMS},
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
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert saved.json()["graph_json"]["nodes"][1]["parameters"]["faces"] == [[0, 1, 2]]
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
        if item["data_type"] == "mesh_measurement_preview"
    )
    standalone = client.post(f"{base}/spatial/mesh-preview", json=PARAMS)
    assert standalone.status_code == 200, standalone.text
    assert artifact["surface_edge_paths"] == standalone.json()["surface_edge_paths"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
    assert artifact["provenance"]["calibration_verified"] is False
