"""GLB Unicode-scalar integrity across direct, API and saved graph execution."""

from __future__ import annotations

import base64
import json
import struct
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_glb_v14 import parse_glb_triangles
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


def glb_with_metadata(*, key: str = "label", value: str = "fish", node: bool = False) -> str:
    """Change JSON metadata only, retaining the original triangle BIN chunk."""
    raw = base64.b64decode(make_glb())
    json_length = struct.unpack_from("<I", raw, 12)[0]
    document: dict[str, Any] = json.loads(raw[20 : 20 + json_length])
    if node:
        document["nodes"][0][key] = value
    else:
        document["extras"] = {key: value}
    json_bytes = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    bin_chunk = raw[20 + json_length :]
    total_length = 20 + len(json_bytes) + len(bin_chunk)
    result = (
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<I4s", len(json_bytes), b"JSON")
        + json_bytes
        + bin_chunk
    )
    return base64.b64encode(result).decode("ascii")


@pytest.mark.parametrize(
    ("key", "value", "node"),
    [
        ("label", "\ud800", False),
        ("\udfff", "label", False),
        ("name", "\udfff", True),
    ],
)
def test_glb_rejects_unpaired_surrogate_in_any_metadata(
    key: str, value: str, node: bool
) -> None:
    with pytest.raises(ValueError, match="unpaired Unicode surrogate"):
        parse_glb_triangles(glb_with_metadata(key=key, value=value, node=node))


def test_valid_unicode_scalar_metadata_preserves_glb_geometry() -> None:
    """A valid surrogate pair in JSON must decode to one Unicode scalar."""
    assert parse_glb_triangles(glb_with_metadata(key="species", value="coral \U0001f41f")) == (
        parse_glb_triangles(make_glb())
    )


@pytest.mark.parametrize(
    ("key", "value", "node"),
    [
        ("label", "\ud800", False),
        ("\udfff", "label", False),
        ("name", "\udfff", True),
    ],
)
def test_invalid_unicode_glb_fails_api_and_saved_workflow_without_artifact(
    client: TestClient, key: str, value: str, node: bool
) -> None:
    project_id = str(create_project(client, "GLB Unicode scalar QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "glb_base64": glb_with_metadata(key=key, value=value, node=node),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler evidence",
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "unpaired Unicode surrogate" in response.text

    graph = {
        "graph_id": "glb-unicode-scalar-qc-v14",
        "name": "GLB Unicode source integrity",
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
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_valid_unicode_glb_saved_workflow_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "GLB valid Unicode scalar")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "glb_base64": glb_with_metadata(key="species", value="coral \U0001f41f"),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler evidence",
    }
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "glb-valid-unicode-v14",
        "name": "GLB valid Unicode provenance",
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
    assert artifact["surface_area_m2"] == standalone.json()["surface_area_m2"]
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
