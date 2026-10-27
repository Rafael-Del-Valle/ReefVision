"""Imported ASCII PLY point-cloud byte binding must survive saved workflow replay."""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_point_cloud_v14 import preview_point_cloud_from_request
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_point_cloud_source_comment_provenance_v14 import (
    COMMENTED_PLY,
    PLY,
)


def _params(ply_text: str, expected_sha256: str | None = None) -> dict[str, Any]:
    return {
        "ply_text": ply_text,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Caller-supplied ruler, not independently verified",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1]],
        "expected_source_payload_sha256": expected_sha256,
    }


def _graph(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": "point-cloud-source-binding-v14",
        "name": "Byte-bound PLY point-cloud measurement",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": parameters},
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


def _run_saved_cloud(client: TestClient, project_id: str, params: dict[str, Any]) -> dict[str, Any]:
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


def test_bound_ply_cloud_has_standalone_and_persisted_workflow_parity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Bound point-cloud PLY")["id"])
    digest = hashlib.sha256(PLY.encode("utf-8")).hexdigest()
    params = _params(PLY, digest)
    direct = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview", json=params
    )
    assert response.status_code == 200, response.text
    standalone = response.json()
    provenance = standalone["provenance"]
    assert provenance == direct["provenance"]
    assert provenance["source_payload_sha256"] == digest
    assert provenance["source_text_sha256"] == digest
    assert provenance["source_payload_size_bytes"] == len(PLY.encode("utf-8"))
    assert provenance["source_payload_integrity_checked"] is True
    assert provenance["calibration_verified"] is False
    assert standalone["measurement_status"] == "caller_supplied_unverified"

    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is True
    assert saved["run"]["status"] == "succeeded"
    artifact = next(
        a["payload_json"]
        for a in saved["artifacts"]
        if a["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["provenance"] == provenance
    assert artifact["selected_point_chords"] == standalone["selected_point_chords"]
    assert artifact["project_id"] == project_id


def test_changed_ply_comment_rejected_despite_identical_geometry(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Stale point-cloud PLY")["id"])
    original = preview_point_cloud_from_request(PointCloudPreviewRequest(**_params(PLY)))
    changed = preview_point_cloud_from_request(PointCloudPreviewRequest(**_params(COMMENTED_PLY)))
    assert original["provenance"]["geometry_sha256"] == changed["provenance"]["geometry_sha256"]
    assert (
        original["provenance"]["source_payload_sha256"]
        != changed["provenance"]["source_payload_sha256"]
    )
    original_sha = hashlib.sha256(PLY.encode("utf-8")).hexdigest()
    params = _params(COMMENTED_PLY, original_sha)
    with pytest.raises(ValueError, match="source SHA-256 does not match"):
        preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview", json=params
    )
    assert response.status_code == 400, response.text

    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is False
    assert saved["run"]["status"] == "failed"
    assert not any(a["data_type"] == "point_cloud_measurement_preview" for a in saved["artifacts"])


@pytest.mark.parametrize("invalid_sha", ["A" * 64, "0" * 63, "x" * 64])
def test_malformed_expected_source_hash_is_rejected(invalid_sha: str) -> None:
    with pytest.raises(PydanticValidationError):
        PointCloudPreviewRequest.model_validate(_params(PLY, invalid_sha))


def test_raw_xyz_cannot_claim_imported_ply_file_binding() -> None:
    with pytest.raises(PydanticValidationError, match="requires an imported"):
        PointCloudPreviewRequest.model_validate(
            {
                "points": [[0, 0, 0], [1, 2, 3]],
                "meters_per_unit": 0.01,
                "calibration_method": "ruler",
                "calibration_evidence": "Unverified",
                "expected_source_payload_sha256": "0" * 64,
            }
        )


def test_unbound_legacy_ply_still_reports_unverified_source_provenance() -> None:
    result = preview_point_cloud_from_request(PointCloudPreviewRequest(**_params(PLY)))
    digest = hashlib.sha256(PLY.encode("utf-8")).hexdigest()
    assert result["provenance"]["source_payload_sha256"] == digest
    assert result["provenance"]["source_payload_integrity_checked"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"
