"""Point-cloud calibration review is independent, source-bound, and never certification."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_point_cloud_v14 import (
    parse_ascii_ply_points,
    preview_point_cloud_from_request,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_point_cloud_source_binding_v14 import (
    _params,
    _run_saved_cloud,
)
from reefvision.tests.test_spatial_point_cloud_source_comment_provenance_v14 import (
    COMMENTED_PLY,
    PLY,
)


def _reviewed_cloud(decision: str = "supports_scale") -> dict:
    params = _params(PLY)
    params.update(
        specimen_id="coral-1",
        observation_id="survey-1",
        observed_at_utc="2026-10-01T12:00:00Z",
    )
    measured = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    params["calibration_review"] = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": decision,
        "independent_review_note": "Compared survey ruler; unverified QC",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": measured["provenance"]["geometry_sha256"],
        "reviewed_source_payload_sha256": measured["provenance"]["source_payload_sha256"],
        "reviewed_specimen_id": "coral-1",
        "reviewed_observation_id": "survey-1",
        "reviewed_observed_at_utc": "2026-10-01T12:00:00Z",
        "reviewed_meters_per_unit": 0.01,
        "reviewed_calibration_method": "ruler",
        "reviewed_calibration_evidence": params["calibration_evidence"],
        "reviewed_relative_scale_uncertainty": 0.1,
    }
    return params


@pytest.mark.parametrize(
    ("decision", "warning"),
    [
        ("supports_scale", None),
        ("disputes_scale", "independent_calibration_review_disputes_scale"),
        ("inconclusive", "independent_calibration_review_inconclusive"),
    ],
)
def test_review_is_provisional_and_attributed(decision: str, warning: str | None) -> None:
    params = _reviewed_cloud(decision)
    result = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    for key, value in params["calibration_review"].items():
        assert result["provenance"]["calibration_review_evidence"][key] == value
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert "independent_calibration_review_not_verification" in result["qc_warnings"]
    if warning is not None:
        assert warning in result["qc_warnings"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reviewed_geometry_sha256", "f" * 64, "source geometry"),
        ("reviewed_specimen_id", "coral-2", "source observation"),
        ("reviewed_observation_id", "survey-2", "source observation"),
        ("reviewed_observed_at_utc", "2026-10-01T13:00:00Z", "source observation"),
        ("reviewed_meters_per_unit", 0.02, "calibration inputs"),
        ("reviewed_calibration_method", "instrument", "calibration inputs"),
        ("reviewed_calibration_evidence", "different ruler", "calibration inputs"),
        ("reviewed_relative_scale_uncertainty", 0.2, "calibration inputs"),
        ("reviewed_at_utc", "2026-09-30T12:00:00Z", "cannot predate bound observation"),
    ],
)
def test_stale_review_is_rejected(field: str, value: object, message: str) -> None:
    params = _reviewed_cloud()
    params["calibration_review"][field] = value
    with pytest.raises(ValueError, match=message):
        preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("independent_reviewer_id", "OPERATOR-1"),
        ("independent_review_note", "   "),
        ("reviewed_geometry_sha256", "bad"),
        ("reviewed_source_payload_sha256", "A" * 64),
        ("reviewed_meters_per_unit", True),
        ("unexpected_verification_claim", True),
    ],
)
def test_invalid_review_attribution_fails_schema(field: str, value: object) -> None:
    params = _reviewed_cloud()
    params["calibration_review"][field] = value
    with pytest.raises(PydanticValidationError):
        PointCloudPreviewRequest.model_validate(params)


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
def test_preconstructed_point_cloud_review_mutation_fails_closed(field: str, value: object) -> None:
    request = PointCloudPreviewRequest.model_validate(_reviewed_cloud())
    assert request.calibration_review is not None
    setattr(request.calibration_review, field, value)
    with pytest.raises(PydanticValidationError):
        preview_point_cloud_from_request(request)


def test_review_rejects_changed_ply_bytes_even_if_xyz_is_unchanged() -> None:
    params = _reviewed_cloud()
    changed = deepcopy(params)
    changed["ply_text"] = COMMENTED_PLY
    original = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    without_review = deepcopy(changed)
    del without_review["calibration_review"]
    modified = preview_point_cloud_from_request(
        PointCloudPreviewRequest.model_validate(without_review)
    )
    assert original["provenance"]["geometry_sha256"] == modified["provenance"]["geometry_sha256"]
    assert (
        original["provenance"]["source_payload_sha256"]
        != modified["provenance"]["source_payload_sha256"]
    )
    with pytest.raises(ValueError, match="imported source bytes"):
        preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(changed))


def test_legacy_unbound_review_is_explicitly_flagged() -> None:
    params = _reviewed_cloud()
    del params["calibration_review"]["reviewed_source_payload_sha256"]
    result = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    assert "independent_calibration_review_source_bytes_unbound" in result["qc_warnings"]
    assert result["provenance"]["calibration_verified"] is False


def test_xyz_points_cannot_claim_imported_file_review() -> None:
    params = _reviewed_cloud()
    del params["ply_text"]
    params["points"] = parse_ascii_ply_points(PLY)
    with pytest.raises(ValueError, match="imported source bytes"):
        preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))


def test_point_cloud_review_frame_binding_rejects_relabel_and_flags_legacy() -> None:
    params = _reviewed_cloud()
    params["coordinate_frame_id"] = "survey-local-A"
    params["calibration_review"]["reviewed_coordinate_frame_id"] = "survey-local-A"
    reviewed = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    assert reviewed["provenance"]["coordinate_registration_verified"] is False
    assert "independent_calibration_review_coordinate_frame_unbound" not in reviewed["qc_warnings"]

    relabeled = deepcopy(params)
    relabeled["coordinate_frame_id"] = "survey-local-B"
    with pytest.raises(ValueError, match="source coordinate frame"):
        preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(relabeled))

    legacy = deepcopy(params)
    del legacy["calibration_review"]["reviewed_coordinate_frame_id"]
    unbound = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(legacy))
    assert "independent_calibration_review_coordinate_frame_unbound" in unbound["qc_warnings"]
    assert unbound["provenance"]["calibration_verified"] is False


def test_reviewed_ply_standalone_and_saved_workflow_match(client: TestClient) -> None:
    project_id = str(create_project(client, "Independent point-cloud calibration QC")["id"])
    params = _reviewed_cloud("disputes_scale")
    params["coordinate_frame_id"] = "survey-frame-1"
    params["calibration_review"]["reviewed_coordinate_frame_id"] = "survey-frame-1"
    params["expected_source_payload_sha256"] = params["calibration_review"][
        "reviewed_source_payload_sha256"
    ]
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(item for item in registry.json() if item["node_type"] == "point_cloud_preview")
    assert "calibration_review" in node["optional_parameters"]
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview", json=params
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is True
    assert saved["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in saved["artifacts"]
        if item["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact == expected
    assert artifact["provenance"]["calibration_verified"] is False
    assert "independent_calibration_review_disputes_scale" in artifact["qc_warnings"]


def test_changed_reviewed_source_fails_saved_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Reject stale reviewed point cloud")["id"])
    params = _reviewed_cloud()
    params["ply_text"] = COMMENTED_PLY
    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is False
    assert saved["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "point_cloud_measurement_preview" for item in saved["artifacts"]
    )


def test_changed_reviewed_coordinate_frame_fails_saved_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Reject relabeled reviewed point cloud")["id"])
    params = _reviewed_cloud()
    params["coordinate_frame_id"] = "survey-frame-B"
    params["calibration_review"]["reviewed_coordinate_frame_id"] = "survey-frame-A"
    with pytest.raises(ValueError, match="source coordinate frame"):
        preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is False
    assert saved["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "point_cloud_measurement_preview" for item in saved["artifacts"]
    )


@pytest.mark.parametrize(
    ("reviewed_at_utc", "invalid"),
    [
        ("2026-10-01T06:59:59-05:00", True),
        ("2026-10-01T07:00:00-05:00", False),
        ("2026-10-02T07:00:00-05:00", False),
    ],
)
def test_point_cloud_review_chronology_uses_timezone_aware_instants(
    reviewed_at_utc: str, invalid: bool
) -> None:
    params = _reviewed_cloud()
    params["calibration_review"]["reviewed_at_utc"] = reviewed_at_utc
    if invalid:
        with pytest.raises(PydanticValidationError, match="cannot predate bound observation"):
            PointCloudPreviewRequest.model_validate(params)
        return

    result = preview_point_cloud_from_request(PointCloudPreviewRequest.model_validate(params))
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_point_cloud_review_chronology_fails_saved_workflow(client: TestClient) -> None:
    """Invalid review chronology must not produce a persisted measurement artifact."""
    project_id = str(create_project(client, "Point-cloud review chronology")["id"])
    params = _reviewed_cloud()
    params["calibration_review"]["reviewed_at_utc"] = "2026-09-30T12:00:00Z"

    with pytest.raises(PydanticValidationError, match="cannot predate bound observation"):
        PointCloudPreviewRequest.model_validate(params)
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview", json=params
    )
    assert response.status_code in (400, 422), response.text
    assert "cannot predate bound observation" in response.text

    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is False
    assert saved["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "point_cloud_measurement_preview" for item in saved["artifacts"]
    )
