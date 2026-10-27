"""Imported mesh source bytes remain distinguishable from parsed geometry identity."""

from __future__ import annotations

import base64
import hashlib
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_cross_format_v14 import COMMON, OBJ, PLY
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [
        ("obj_text", OBJ),
        ("ply_text", PLY),
        ("glb_base64", make_glb()),
    ],
    ids=["obj", "ply", "glb"],
)
def test_source_byte_fingerprint_survives_standalone_and_saved_workflow(
    client: TestClient, source_key: str, source_value: str
) -> None:
    project_id = str(create_project(client, "Source content provenance")["id"])
    base = f"/api/v1/projects/{project_id}"
    params: dict[str, Any] = {**COMMON, source_key: source_value}
    expected_bytes = (
        base64.b64decode(source_value, validate=True)
        if source_key == "glb_base64"
        else source_value.encode("utf-8")
    )
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()

    direct = preview_from_request(MeshPreviewRequest.model_validate(params))
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    assert direct["provenance"]["source_payload_sha256"] == expected_sha
    assert direct["provenance"]["source_payload_size_bytes"] == len(expected_bytes)
    assert standalone.json()["provenance"] == direct["provenance"]
    assert direct["provenance"]["calibration_verified"] is False
    assert direct["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": f"mesh-source-fingerprint-{source_key}",
        "name": "Auditable imported mesh source identity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
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
    assert artifact["provenance"] == direct["provenance"]
    assert artifact["surface_area_m2"] == direct["surface_area_m2"]
    assert artifact["project_id"] == project_id
    assert artifact["measurement_status"] == "caller_supplied_unverified"


def test_source_bytes_and_parsed_geometry_have_separate_fingerprints() -> None:
    obj = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=OBJ))
    ply = preview_from_request(MeshPreviewRequest(**COMMON, ply_text=PLY))
    obj_whitespace = preview_from_request(
        MeshPreviewRequest(**COMMON, obj_text=OBJ.replace("v 2 0 0\\n", "v 2 0 0  \\n"))
    )
    assert obj["provenance"]["geometry_sha256"] == ply["provenance"]["geometry_sha256"]
    assert obj["provenance"]["geometry_sha256"] == obj_whitespace["provenance"]["geometry_sha256"]
    assert obj["provenance"]["source_payload_sha256"] != ply["provenance"]["source_payload_sha256"]
    assert (
        obj["provenance"]["source_payload_sha256"]
        != obj_whitespace["provenance"]["source_payload_sha256"]
    )


def test_indexed_triangles_do_not_claim_an_imported_source_file() -> None:
    result = preview_from_request(
        MeshPreviewRequest(
            **COMMON,
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces=[[0, 1, 2]],
        )
    )
    assert result["provenance"]["source_format"] == "indexed_triangles"
    assert result["provenance"]["source_payload_sha256"] is None
    assert result["provenance"]["source_payload_size_bytes"] is None
    assert len(result["provenance"]["geometry_sha256"]) == 64
