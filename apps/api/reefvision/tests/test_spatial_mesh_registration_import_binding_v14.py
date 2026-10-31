"""Registration evidence must bind to imported bytes and project asset identities."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshPreviewRequest,
    MeshRegistrationEvidence,
)
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project


BEFORE_OBJ = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
AFTER_OBJ = "v 0 0 0\nv 1 0 0\nv 0 2 0\nf 1 2 3\n"
ASSET_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
)


def _params(obj_text: str, observation_id: str, date: str, frame: str) -> dict:
    return {
        "obj_text": obj_text,
        "meters_per_unit": 1.0,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field scale reference",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "colony-1",
        "observation_id": observation_id,
        "observed_at_utc": date,
        "coordinate_frame_id": frame,
    }


def _inputs() -> tuple[dict, dict]:
    return (
        _params(BEFORE_OBJ, "scan-1", "2026-10-01T12:00:00Z", "frame-a"),
        _params(AFTER_OBJ, "scan-2", "2026-10-02T12:00:00Z", "frame-b"),
    )


def _previews(project_id: str, *, asset_ids: bool = False) -> tuple[dict, dict]:
    first_params, second_params = _inputs()
    first = preview_from_request(MeshPreviewRequest.model_validate(first_params))
    second = preview_from_request(MeshPreviewRequest.model_validate(second_params))
    for index, preview in enumerate((first, second)):
        preview["project_id"] = project_id
        if asset_ids:
            preview["provenance"]["spatial_source_asset_id"] = ASSET_IDS[index]
    return first, second


def _registration(before: dict, after: dict, *, asset_ids: bool = False) -> dict:
    first = before["provenance"]
    second = after["provenance"]
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "landmark",
        "rms_residual_m": 0.02,
        "correspondence_count": 6,
        "evidence_note": "Provisional field registration, not certified",
        "source_geometry_sha256": first["geometry_sha256"],
        "target_geometry_sha256": second["geometry_sha256"],
        "source_payload_sha256": first["source_payload_sha256"],
        "target_payload_sha256": second["source_payload_sha256"],
    }
    if asset_ids:
        evidence["source_spatial_source_asset_id"] = first["spatial_source_asset_id"]
        evidence["target_spatial_source_asset_id"] = second["spatial_source_asset_id"]
    return evidence


def test_registration_import_bindings_are_provisional_and_auditable() -> None:
    before, after = _previews("project-1", asset_ids=True)
    evidence = _registration(before, after, asset_ids=True)
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert result["provenance"]["registration_evidence"] == evidence
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert "registration_source_payload_binding_unavailable" not in result["qc_warnings"]
    assert "registration_spatial_source_asset_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["review_evidence_bundle_sha256"] is not None


def test_registration_reexport_with_identical_geometry_rejects_stale_bytes() -> None:
    before, after = _previews("project-1", asset_ids=True)
    evidence = _registration(before, after, asset_ids=True)
    changed_params = _inputs()[1]
    changed_params["obj_text"] += "# re-exported from same vertices\n"
    reexport = preview_from_request(MeshPreviewRequest.model_validate(changed_params))
    reexport["project_id"] = "project-1"
    reexport["provenance"]["spatial_source_asset_id"] = ASSET_IDS[1]
    assert reexport["provenance"]["geometry_sha256"] == after["provenance"]["geometry_sha256"]
    assert reexport["provenance"]["source_payload_sha256"] != after["provenance"][
        "source_payload_sha256"
    ]
    with pytest.raises(ValueError, match="both imported source payloads"):
        compare_mesh_observations(before, reexport, registration_evidence=evidence)


def test_registration_reimport_with_identical_bytes_rejects_stale_asset() -> None:
    before, after = _previews("project-1", asset_ids=True)
    evidence = _registration(before, after, asset_ids=True)
    other = deepcopy(after)
    other["provenance"]["spatial_source_asset_id"] = (
        "33333333-3333-4333-8333-333333333333"
    )
    assert other["provenance"]["source_payload_sha256"] == after["provenance"][
        "source_payload_sha256"
    ]
    with pytest.raises(ValueError, match="both spatial source asset IDs"):
        compare_mesh_observations(before, other, registration_evidence=evidence)


@pytest.mark.parametrize(
    "missing",
    ["source_payload_sha256", "target_payload_sha256",
     "source_spatial_source_asset_id", "target_spatial_source_asset_id"],
)
def test_registration_requires_complete_import_bindings(missing: str) -> None:
    before, after = _previews("project-1", asset_ids=True)
    evidence = _registration(before, after, asset_ids=True)
    del evidence[missing]
    with pytest.raises(PydanticValidationError, match="requires both"):
        MeshRegistrationEvidence.model_validate(evidence)


def test_registration_rejects_mutated_binding_after_initial_validation() -> None:
    before, after = _previews("project-1", asset_ids=True)
    evidence = MeshRegistrationEvidence.model_validate(
        _registration(before, after, asset_ids=True)
    )
    evidence.target_payload_sha256 = "a" * 64
    with pytest.raises(ValueError, match="both imported source payloads"):
        compare_mesh_observations(before, after, registration_evidence=evidence)
    evidence.target_payload_sha256 = None
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def test_legacy_registration_import_bindings_are_flagged_not_verified() -> None:
    before, after = _previews("project-1", asset_ids=True)
    evidence = _registration(before, after, asset_ids=True)
    for key in (
        "source_payload_sha256",
        "target_payload_sha256",
        "source_spatial_source_asset_id",
        "target_spatial_source_asset_id",
    ):
        del evidence[key]
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert "registration_source_payload_binding_unavailable" in result["qc_warnings"]
    assert "registration_spatial_source_asset_binding_unavailable" in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


def test_import_bound_registration_standalone_and_saved_workflow_parity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Import-bound registration workflow")["id"])
    base = f"/api/v1/projects/{project_id}"
    before, after = _inputs()
    asset_ids = []
    for filename, source in (("early.obj", BEFORE_OBJ), ("late.obj", AFTER_OBJ)):
        uploaded = client.post(
            f"{base}/spatial/assets",
            files={"file": (filename, source.encode("utf-8"))},
        )
        assert uploaded.status_code == 201, uploaded.text
        asset_ids.append(uploaded.json()["id"])
    before.pop("obj_text")
    after.pop("obj_text")
    before["asset_id"] = asset_ids[0]
    after["asset_id"] = asset_ids[1]
    previews = _previews(project_id)
    for preview, asset_id in zip(previews, asset_ids, strict=True):
        preview["provenance"]["spatial_source_asset_id"] = asset_id
    evidence = _registration(*previews, asset_ids=True)
    endpoint = f"{base}/spatial/mesh-longitudinal-comparison"
    standalone = client.post(
        endpoint,
        json={"before": before, "after": after, "registration_evidence": evidence},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["registration_evidence"] == evidence
    assert "registration_source_payload_binding_unavailable" not in expected["qc_warnings"]
    assert "registration_spatial_source_asset_binding_unavailable" not in expected[
        "qc_warnings"
    ]

    graph = {
        "graph_id": "registration-source-bound-v14",
        "name": "Source-bound provisional registration",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {
                "node_id": "compare",
                "node_type": "mesh_longitudinal_comparison",
                "parameters": {"registration_evidence": evidence},
            },
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact == expected

    # A new export with identical geometry must fail in both execution paths.
    reexport = (AFTER_OBJ + "# revised export comment\\n").encode("utf-8")
    uploaded_reexport = client.post(
        f"{base}/spatial/assets",
        files={"file": ("late-reexport.obj", reexport)},
    )
    assert uploaded_reexport.status_code == 201, uploaded_reexport.text
    changed_after = {**after, "asset_id": uploaded_reexport.json()["id"]}
    assert sha256(reexport).hexdigest() != evidence["target_payload_sha256"]
    rejected = client.post(
        endpoint,
        json={
            "before": before,
            "after": changed_after,
            "registration_evidence": evidence,
        },
    )
    assert rejected.status_code == 400, rejected.text
    graph["nodes"][2]["parameters"] = changed_after
    saved_bad = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved_bad.status_code == 201, saved_bad.text
    run_bad = client.post(
        f"{base}/workflow-runs", json={"graph_record_id": saved_bad.json()["id"]}
    )
    assert run_bad.status_code == 202, run_bad.text
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run_bad.json()["job_id"])
    )
    failed = client.get(f"/api/v1/workflow-runs/{run_bad.json()['id']}")
    assert failed.status_code == 200, failed.text
    assert failed.json()["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "mesh_longitudinal_comparison"
        for item in failed.json()["artifacts"]
    )
