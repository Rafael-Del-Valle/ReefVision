"""Independent calibration review is source-bound audit evidence, not certification."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_cross_format_v14 import PLY
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


def _mesh() -> dict:
    return {
        "vertices": [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Survey ruler in source photographs",
        "relative_scale_uncertainty": 0.05,
        "specimen_id": "colony-1",
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
    }


def _reviewed_mesh(decision: str = "supports_scale") -> dict:
    payload = _mesh()
    measured = preview_from_request(MeshPreviewRequest.model_validate(payload))
    payload["calibration_review"] = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": decision,
        "independent_review_note": "Checked ruler against source image; provisional QC only",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": measured["provenance"]["geometry_sha256"],
        "reviewed_specimen_id": "colony-1",
        "reviewed_observation_id": "survey-1",
        "reviewed_observed_at_utc": "2026-10-01T12:00:00Z",
        "reviewed_meters_per_unit": 0.1,
        "reviewed_calibration_method": "ruler",
        "reviewed_calibration_evidence": "Survey ruler in source photographs",
        "reviewed_relative_scale_uncertainty": 0.05,
    }
    return payload


_OBJ_SOURCE = "v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n"


def _reviewed_imported_mesh() -> dict:
    payload = _mesh()
    del payload["vertices"]
    del payload["faces"]
    payload["obj_text"] = _OBJ_SOURCE
    measured = preview_from_request(MeshPreviewRequest.model_validate(payload))
    review = deepcopy(_reviewed_mesh()["calibration_review"])
    review["reviewed_geometry_sha256"] = measured["provenance"]["geometry_sha256"]
    review["reviewed_source_payload_sha256"] = measured["provenance"]["source_payload_sha256"]
    payload["calibration_review"] = review
    return payload


@pytest.mark.parametrize(
    ("decision", "extra_warning"),
    [
        ("supports_scale", None),
        ("disputes_scale", "independent_calibration_review_disputes_scale"),
        ("inconclusive", "independent_calibration_review_inconclusive"),
    ],
)
def test_review_is_recorded_without_certifying_calibration(
    decision: str, extra_warning: str | None
) -> None:
    payload = _reviewed_mesh(decision)
    result = preview_from_request(MeshPreviewRequest.model_validate(payload))
    for key, value in payload["calibration_review"].items():
        assert result["provenance"]["calibration_review_evidence"][key] == value
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert "independent_calibration_review_not_verification" in result["qc_warnings"]
    if extra_warning is not None:
        assert extra_warning in result["qc_warnings"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reviewed_geometry_sha256", "f" * 64, "source geometry"),
        ("reviewed_specimen_id", "colony-2", "source observation"),
        ("reviewed_observation_id", "survey-2", "source observation"),
        ("reviewed_observed_at_utc", "2026-10-02T12:00:00Z", "source observation"),
        ("reviewed_meters_per_unit", 0.2, "calibration inputs"),
        ("reviewed_calibration_method", "instrument", "calibration inputs"),
        ("reviewed_calibration_evidence", "Different ruler", "calibration inputs"),
        ("reviewed_relative_scale_uncertainty", 0.1, "calibration inputs"),
        ("reviewed_at_utc", "2026-09-30T12:00:00Z", "cannot predate bound observation"),
    ],
)
def test_review_rejects_stale_geometry_calibration_or_time(
    field: str, value: object, message: str
) -> None:
    payload = _reviewed_mesh()
    payload["calibration_review"][field] = value
    with pytest.raises(ValueError, match=message):
        preview_from_request(MeshPreviewRequest.model_validate(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("independent_reviewer_id", "operator-1"),
        ("independent_reviewer_id", "OPERATOR-1"),
        ("independent_review_note", " \t "),
        ("reviewed_calibration_evidence", " \t "),
        ("reviewed_meters_per_unit", True),
        ("reviewed_geometry_sha256", "not-a-sha"),
        ("reviewed_source_payload_sha256", "not-a-sha"),
        ("unexpected_verification_claim", True),
    ],
)
def test_review_schema_fails_closed_on_invalid_attribution(field: str, value: object) -> None:
    payload = _reviewed_mesh()
    payload["calibration_review"][field] = value
    with pytest.raises(PydanticValidationError):
        MeshPreviewRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("independent_reviewer_id", "OPERATOR-1"),
        ("independent_review_decision", "verified"),
        ("independent_review_note", "   "),
        ("reviewed_geometry_sha256", "not-a-digest"),
        ("reviewed_meters_per_unit", -0.1),
        ("reviewed_coordinate_frame_id", "invalid frame label"),
    ],
)
def test_preconstructed_mesh_review_mutation_fails_closed(field: str, value: object) -> None:
    request = MeshPreviewRequest.model_validate(_reviewed_mesh())
    assert request.calibration_review is not None
    # Assignment validation is intentionally not enabled on the shared schema.
    # The service must not trust a model that was changed after initial parsing.
    setattr(request.calibration_review, field, value)
    with pytest.raises(PydanticValidationError):
        preview_from_request(request)


def test_reviewed_import_rejects_changed_bytes_with_identical_geometry() -> None:
    payload = _reviewed_imported_mesh()
    original = preview_from_request(MeshPreviewRequest.model_validate(payload))
    changed = deepcopy(payload)
    changed["obj_text"] = _OBJ_SOURCE.replace("v 2 0 0\n", "v 2 0 0  \n")
    unreviewed = deepcopy(changed)
    del unreviewed["calibration_review"]
    changed_preview = preview_from_request(MeshPreviewRequest.model_validate(unreviewed))
    assert (
        original["provenance"]["geometry_sha256"]
        == changed_preview["provenance"]["geometry_sha256"]
    )
    assert (
        original["provenance"]["source_payload_sha256"]
        != changed_preview["provenance"]["source_payload_sha256"]
    )
    with pytest.raises(ValueError, match="imported source bytes"):
        preview_from_request(MeshPreviewRequest.model_validate(changed))
    for key, value in payload["calibration_review"].items():
        assert original["provenance"]["calibration_review_evidence"][key] == value
    assert "independent_calibration_review_source_bytes_unbound" not in original["qc_warnings"]


def test_legacy_import_review_without_byte_binding_is_flagged() -> None:
    payload = _reviewed_imported_mesh()
    del payload["calibration_review"]["reviewed_source_payload_sha256"]
    result = preview_from_request(MeshPreviewRequest.model_validate(payload))
    assert "independent_calibration_review_source_bytes_unbound" in result["qc_warnings"]
    assert result["provenance"]["calibration_verified"] is False


def test_indexed_mesh_review_cannot_claim_imported_source_bytes() -> None:
    payload = _reviewed_mesh()
    payload["calibration_review"]["reviewed_source_payload_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="imported source bytes"):
        preview_from_request(MeshPreviewRequest.model_validate(payload))


def test_review_is_bound_to_source_coordinate_frame_without_claiming_registration() -> None:
    payload = _reviewed_mesh()
    payload["coordinate_frame_id"] = "survey-local-A"
    payload["calibration_review"]["reviewed_coordinate_frame_id"] = "survey-local-A"
    reviewed = preview_from_request(MeshPreviewRequest.model_validate(payload))
    assert reviewed["provenance"]["coordinate_frame_id"] == "survey-local-A"
    assert reviewed["provenance"]["coordinate_registration_verified"] is False
    assert "independent_calibration_review_coordinate_frame_unbound" not in reviewed["qc_warnings"]

    relabeled = deepcopy(payload)
    relabeled["coordinate_frame_id"] = "survey-local-B"
    with pytest.raises(ValueError, match="source coordinate frame"):
        preview_from_request(MeshPreviewRequest.model_validate(relabeled))

    legacy = deepcopy(payload)
    del legacy["calibration_review"]["reviewed_coordinate_frame_id"]
    unbound = preview_from_request(MeshPreviewRequest.model_validate(legacy))
    assert "independent_calibration_review_coordinate_frame_unbound" in unbound["qc_warnings"]
    assert unbound["provenance"]["calibration_verified"] is False


def test_legacy_mesh_without_review_remains_unverified() -> None:
    result = preview_from_request(MeshPreviewRequest.model_validate(_mesh()))
    assert "calibration_review_evidence" not in result["provenance"]
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [("obj_text", _OBJ_SOURCE), ("ply_text", PLY), ("glb_base64", make_glb())],
    ids=["obj", "ascii-ply", "glb"],
)
def test_saved_workflow_and_standalone_review_are_identical(
    client: TestClient, source_key: str, source_value: str
) -> None:
    project_id = str(create_project(client, "Independent calibration review")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _reviewed_imported_mesh()
    if source_key != "obj_text":
        params.pop("obj_text")
        params[source_key] = source_value
        review = params.pop("calibration_review")
        measured = preview_from_request(MeshPreviewRequest.model_validate(params))
        review["reviewed_geometry_sha256"] = measured["provenance"]["geometry_sha256"]
        review["reviewed_source_payload_sha256"] = measured["provenance"]["source_payload_sha256"]
        params["calibration_review"] = review
    params["expected_source_payload_sha256"] = params["calibration_review"][
        "reviewed_source_payload_sha256"
    ]
    params["calibration_review"]["independent_review_decision"] = "disputes_scale"
    params["coordinate_frame_id"] = "survey-frame-1"
    params["calibration_review"]["reviewed_coordinate_frame_id"] = "survey-frame-1"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["source_payload_integrity_checked"] is True
    assert (
        expected["provenance"]["source_payload_sha256"] == params["expected_source_payload_sha256"]
    )
    assert expected["provenance"]["calibration_verified"] is False
    graph = {
        "graph_id": "independent-calibration-review-v14",
        "name": "Provisional reviewed mesh",
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
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    mesh_node = next(
        item for item in registry.json() if item["node_type"] == "mesh_surface_preview"
    )
    assert "calibration_review" in mesh_node["optional_parameters"]
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["calibration_review"]
        == params["calibration_review"]
    )
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
    assert artifact == expected
    assert "independent_calibration_review_disputes_scale" in artifact["qc_warnings"]


def test_modified_review_does_not_mutate_original_measurement() -> None:
    payload = _reviewed_mesh()
    baseline = preview_from_request(MeshPreviewRequest.model_validate(payload))
    revised = deepcopy(payload)
    revised["calibration_review"]["reviewed_geometry_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="source geometry"):
        preview_from_request(MeshPreviewRequest.model_validate(revised))
    for key, value in payload["calibration_review"].items():
        assert baseline["provenance"]["calibration_review_evidence"][key] == value


@pytest.mark.parametrize(
    ("reviewed_at_utc", "invalid"),
    [
        ("2026-10-01T06:59:59-05:00", True),
        ("2026-10-01T07:00:00-05:00", False),
        ("2026-10-02T07:00:00-05:00", False),
    ],
)
def test_calibration_review_chronology_is_checked_as_timezone_aware_instants(
    reviewed_at_utc: str, invalid: bool
) -> None:
    """A dated review cannot predate its claimed observation, even before execution."""
    payload = _reviewed_mesh()
    payload["calibration_review"]["reviewed_at_utc"] = reviewed_at_utc
    if invalid:
        with pytest.raises(PydanticValidationError, match="cannot predate bound observation"):
            MeshPreviewRequest.model_validate(payload)
        return

    result = preview_from_request(MeshPreviewRequest.model_validate(payload))
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_review_chronology_fails_closed_in_saved_graph(client: TestClient) -> None:
    """A persisted executable graph must not publish a preview with impossible review dates."""
    project_id = str(create_project(client, "Calibration review chronology replay")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = _reviewed_imported_mesh()
    params["calibration_review"]["reviewed_at_utc"] = "2026-09-30T12:00:00Z"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code in (400, 422), standalone.text
    assert "cannot predate bound observation" in standalone.text

    graph = {
        "graph_id": "calibration-review-chronology-v14",
        "name": "Reject impossible independent review chronology",
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
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["calibration_review"]
        == params["calibration_review"]
    )
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
        item["data_type"] == "mesh_measurement_preview" for item in detail.json()["artifacts"]
    )
