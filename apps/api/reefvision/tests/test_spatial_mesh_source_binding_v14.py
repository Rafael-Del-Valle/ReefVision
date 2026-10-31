"""Imported mesh source hash bindings reject silent source-file changes on replay."""

from __future__ import annotations

import base64
import hashlib
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_cross_format_v14 import COMMON, OBJ, PLY
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


def _graph(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": "mesh-source-binding-v14",
        "name": "Fail-closed source identity replay",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": parameters},
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


def _run_saved_mesh(client: TestClient, project_id: str, params: dict[str, Any]) -> dict[str, Any]:
    base = f"/api/v1/projects/{project_id}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": _graph(params)})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    return {"completed": completed, **detail.json()}


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [
        ("obj_text", OBJ),
        ("ply_text", PLY),
        ("glb_base64", make_glb()),
    ],
    ids=["obj", "ascii-ply", "glb"],
)
def test_matching_source_binding_persists_through_standalone_and_saved_workflow(
    client: TestClient, source_key: str, source_value: str
) -> None:
    project_id = str(create_project(client, "Bound imported mesh source")["id"])
    source_bytes = (
        base64.b64decode(source_value, validate=True)
        if source_key == "glb_base64"
        else source_value.encode("utf-8")
    )
    digest = hashlib.sha256(source_bytes).hexdigest()
    params: dict[str, Any] = {
        **COMMON,
        source_key: source_value,
        "expected_source_payload_sha256": digest,
    }
    direct = preview_from_request(MeshPreviewRequest.model_validate(params))
    standalone = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert direct["provenance"] == expected["provenance"]
    assert expected["provenance"]["source_payload_sha256"] == digest
    assert expected["provenance"]["source_payload_integrity_checked"] is True
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["measurement_status"] == "caller_supplied_unverified"

    detail = _run_saved_mesh(client, project_id, params)
    assert detail["completed"] is True
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["provenance"] == expected["provenance"]
    assert artifact["surface_area_m2"] == expected["surface_area_m2"]
    assert artifact["project_id"] == project_id


def test_modified_obj_source_is_rejected_even_when_parsed_geometry_is_unchanged(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Detect stale mesh file bytes")["id"])
    original_sha = hashlib.sha256(OBJ.encode("utf-8")).hexdigest()
    changed_obj = OBJ.replace("v 2 0 0\n", "v 2 0 0  \n")
    assert changed_obj != OBJ
    original = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=OBJ))
    modified = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=changed_obj))
    before = original["provenance"]
    after = modified["provenance"]
    assert before["geometry_sha256"] == after["geometry_sha256"]
    assert before["source_payload_sha256"] != after["source_payload_sha256"]
    params = {
        **COMMON,
        "obj_text": changed_obj,
        "expected_source_payload_sha256": original_sha,
    }
    with pytest.raises(ValueError, match="source SHA-256 does not match"):
        preview_from_request(MeshPreviewRequest.model_validate(params))
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "source SHA-256 does not match" in response.text

    detail = _run_saved_mesh(client, project_id, params)
    assert detail["completed"] is False
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


@pytest.mark.parametrize("bad_hash", ["A" * 64, "0" * 63, "x" * 64])
def test_malformed_source_hash_rejected_at_schema_boundary(bad_hash: str) -> None:
    with pytest.raises(PydanticValidationError):
        MeshPreviewRequest.model_validate(
            {**COMMON, "obj_text": OBJ, "expected_source_payload_sha256": bad_hash}
        )


def test_indexed_triangles_cannot_claim_imported_file_binding() -> None:
    with pytest.raises(PydanticValidationError, match="requires an imported"):
        MeshPreviewRequest.model_validate(
            {
                **COMMON,
                "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "faces": [[0, 1, 2]],
                "expected_source_payload_sha256": "0" * 64,
            }
        )


def test_legacy_import_without_expected_hash_remains_unbound() -> None:
    result = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=OBJ))
    expected_sha = hashlib.sha256(OBJ.encode("utf-8")).hexdigest()
    assert result["provenance"]["source_payload_sha256"] == expected_sha
    assert result["provenance"]["source_payload_integrity_checked"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize(
    "invalid_face",
    [
        "f 1/ 2 3",
        "f 1/2/3/4 2 3",
        "f 1//0 2 3",
    ],
)
def test_malformed_obj_rejected_by_api_and_persisted_workflow(
    client: TestClient, invalid_face: str
) -> None:
    project_id = str(create_project(client, "Reject malformed OBJ references")["id"])
    obj_text = f"v 0 0 0\nv 2 0 0\nv 0 3 0\n{invalid_face}\n"
    params = {**COMMON, "obj_text": obj_text}
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "OBJ line 4:" in response.text

    detail = _run_saved_mesh(client, project_id, params)
    assert detail["completed"] is False
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


ATTRIBUTE_RECORDS = (
    "v 0 0 0\n"
    "v 2 0 0\n"
    "v 0 3 0\n"
    "vt 0 0\n"
    "vt 1 0\n"
    "vt 0 1\n"
    "vn 0 0 1\n"
)


@pytest.mark.parametrize(
    "invalid_face",
    [
        "f 1/4/1 2/2/1 3/3/1",
        "f 1/-4/1 2/2/1 3/3/1",
        "f 1/1/2 2/2/1 3/3/1",
    ],
)
def test_declared_obj_attribute_index_replay_fails_closed(
    client: TestClient, invalid_face: str
) -> None:
    project_id = str(create_project(client, "Reject stale OBJ texture or normal references")["id"])
    params = {**COMMON, "obj_text": ATTRIBUTE_RECORDS + invalid_face + "\n"}
    with pytest.raises(ValueError, match="face attribute index out of bounds"):
        preview_from_request(MeshPreviewRequest.model_validate(params))
    response = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert response.status_code == 400, response.text
    assert "face attribute index out of bounds" in response.text
    detail = _run_saved_mesh(client, project_id, params)
    assert detail["completed"] is False
    assert detail["run"]["status"] == "failed"
    assert not any(item["data_type"] == "mesh_measurement_preview" for item in detail["artifacts"])


def test_declared_obj_attribute_indices_preserve_saved_workflow_measurement(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Bound OBJ texture and normal indices")["id"])
    params = {**COMMON, "obj_text": ATTRIBUTE_RECORDS + "f 1/1/1 2/-2/1 3/-1/-1\n"}
    standalone = client.post(f"/api/v1/projects/{project_id}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    detail = _run_saved_mesh(client, project_id, params)
    assert detail["completed"] is True
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["surface_area_m2"] == standalone.json()["surface_area_m2"]
    assert artifact["provenance"] == standalone.json()["provenance"]
    assert artifact["measurement_status"] == "caller_supplied_unverified"
