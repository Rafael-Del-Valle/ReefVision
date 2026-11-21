"""Provisional mesh registration must not silently outlive its source geometry."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.spatial_mesh_preview_v14 import MeshRegistrationEvidence
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations


def _observations() -> tuple[dict, dict]:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "project_id": "study-1",
        "surface_area_m2": 1.0,
        "provenance": {
            "specimen_id": "coral-1",
            "observation_id": "scan-1",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "coordinate_frame_id": "survey-a",
            "geometry_sha256": "a" * 64,
            "calibration_verified": False,
        },
    }
    after = deepcopy(before)
    after["provenance"].update(
        observation_id="scan-2",
        observed_at_utc="2026-10-02T12:00:00Z",
        coordinate_frame_id="survey-b",
        geometry_sha256="b" * 64,
    )
    return before, after


def _evidence() -> dict:
    return {
        "source_frame_id": "survey-a",
        "target_frame_id": "survey-b",
        "method": "landmark",
        "rms_residual_m": 0.02,
        "correspondence_count": 6,
        "evidence_note": "Provisional six-point registration; not independently verified",
        "source_geometry_sha256": "a" * 64,
        "target_geometry_sha256": "b" * 64,
    }


def test_geometry_bound_registration_remains_provisional() -> None:
    before, after = _observations()
    evidence = _evidence()
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert result["provenance"]["registration_evidence"] == evidence
    assert "registration_geometry_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


@pytest.mark.parametrize("changed", ["source", "target"])
def test_registration_reuse_against_different_geometry_is_rejected(changed: str) -> None:
    before, after = _observations()
    record = before if changed == "source" else after
    record["provenance"]["geometry_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="source geometry fingerprints"):
        compare_mesh_observations(before, after, registration_evidence=_evidence())


def test_partial_and_malformed_registration_geometry_binding_is_rejected() -> None:
    evidence = _evidence()
    del evidence["target_geometry_sha256"]
    with pytest.raises(PydanticValidationError, match="requires both SHA-256"):
        MeshRegistrationEvidence.model_validate(evidence)
    evidence["target_geometry_sha256"] = "NOT-A-SHA"
    with pytest.raises(PydanticValidationError):
        MeshRegistrationEvidence.model_validate(evidence)


def test_legacy_unbound_registration_remains_usable_with_explicit_qc() -> None:
    before, after = _observations()
    evidence = _evidence()
    del evidence["source_geometry_sha256"]
    del evidence["target_geometry_sha256"]
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert "registration_geometry_binding_unavailable" in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


def test_mutated_registration_model_is_revalidated_against_geometry() -> None:
    before, after = _observations()
    evidence = MeshRegistrationEvidence.model_validate(_evidence())
    evidence.target_geometry_sha256 = "c" * 64
    with pytest.raises(ValueError, match="source geometry fingerprints"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def test_mutated_registration_model_cannot_remove_half_of_geometry_binding() -> None:
    before, after = _observations()
    evidence = MeshRegistrationEvidence.model_validate(_evidence())
    evidence.target_geometry_sha256 = None
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def _bound_evidence() -> dict:
    return {
        **_evidence(),
        "project_id": "study-1",
        "source_observation_id": "scan-1",
        "target_observation_id": "scan-2",
        "source_observed_at_utc": "2026-10-01T12:00:00Z",
        "target_observed_at_utc": "2026-10-02T12:00:00Z",
    }


def test_registration_project_observation_and_time_bindings_are_preserved() -> None:
    before, after = _observations()
    evidence = _bound_evidence()
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert result["provenance"]["registration_evidence"] == evidence
    for warning in (
        "registration_project_binding_unavailable",
        "registration_observation_binding_unavailable",
        "registration_timepoint_binding_unavailable",
    ):
        assert warning not in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("project_id", "other-study", "project ID"),
        ("source_observation_id", "other-scan", "observation IDs"),
        ("target_observation_id", "other-scan", "observation IDs"),
        ("source_observed_at_utc", "2026-09-30T12:00:00Z", "observation timestamps"),
        ("target_observed_at_utc", "2026-10-03T12:00:00Z", "observation timestamps"),
    ],
)
def test_registration_binding_rejects_stale_evidence(field: str, value: str, message: str) -> None:
    before, after = _observations()
    evidence = _bound_evidence()
    evidence[field] = value
    with pytest.raises(ValueError, match=message):
        compare_mesh_observations(before, after, registration_evidence=evidence)


@pytest.mark.parametrize("missing", ["target_observation_id", "target_observed_at_utc"])
def test_registration_rejects_partial_observation_or_time_binding(missing: str) -> None:
    evidence = _bound_evidence()
    del evidence[missing]
    with pytest.raises(PydanticValidationError, match="requires both"):
        MeshRegistrationEvidence.model_validate(evidence)


def test_registration_time_binding_compares_instants_not_timezone_strings() -> None:
    before, after = _observations()
    evidence = _bound_evidence()
    evidence["target_observed_at_utc"] = "2026-10-02T07:00:00-05:00"
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert "registration_timepoint_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


def test_legacy_registration_missing_observation_bindings_is_flagged() -> None:
    before, after = _observations()
    result = compare_mesh_observations(before, after, registration_evidence=_evidence())
    assert "registration_project_binding_unavailable" in result["qc_warnings"]
    assert "registration_observation_binding_unavailable" in result["qc_warnings"]
    assert "registration_timepoint_binding_unavailable" in result["qc_warnings"]


def test_mutated_registration_project_binding_is_revalidated() -> None:
    before, after = _observations()
    evidence = MeshRegistrationEvidence.model_validate(_bound_evidence())
    evidence.project_id = "another-study"
    with pytest.raises(ValueError, match="project ID"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def _reviewed_evidence() -> dict:
    return {
        **_bound_evidence(),
        "registration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "supports_alignment",
        "independent_review_note": "Checked landmarks, not certified alignment",
        "independent_reviewed_at_utc": "2026-10-03T12:00:00Z",
    }


def test_independent_registration_review_stays_provisional() -> None:
    before, after = _observations()
    evidence = _reviewed_evidence()
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert result["provenance"]["registration_evidence"] == evidence
    assert (
        "registration_independent_review_recorded_not_alignment_verification"
        in result["qc_warnings"]
    )
    assert "registration_evidence_requires_independent_review" not in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("independent_reviewer_id", "requires reviewer"),
        ("independent_review_decision", "requires reviewer"),
        ("independent_review_note", "requires reviewer"),
        ("registration_operator_id", "requires operator attribution"),
    ],
)
def test_registration_review_requires_complete_independent_attribution(
    missing: str, message: str
) -> None:
    evidence = _reviewed_evidence()
    del evidence[missing]
    with pytest.raises(PydanticValidationError, match=message):
        MeshRegistrationEvidence.model_validate(evidence)


def test_registration_operator_cannot_self_review() -> None:
    evidence = _reviewed_evidence()
    evidence["independent_reviewer_id"] = "operator-1"
    with pytest.raises(PydanticValidationError, match="must differ"):
        MeshRegistrationEvidence.model_validate(evidence)


def test_registration_review_cannot_predate_later_observation() -> None:
    before, after = _observations()
    evidence = _reviewed_evidence()
    evidence["independent_reviewed_at_utc"] = "2026-10-01T12:00:00Z"
    with pytest.raises(PydanticValidationError, match="cannot predate bound observations"):
        MeshRegistrationEvidence.model_validate(evidence)
    # The standalone comparison intentionally wraps invalid caller evidence.
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def test_registration_review_timestamp_handles_timezone_offsets() -> None:
    before, after = _observations()
    evidence = _reviewed_evidence()
    evidence["independent_reviewed_at_utc"] = "2026-10-03T07:00:00-05:00"
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert "registration_independent_review_timestamp_unavailable" not in result["qc_warnings"]


def test_legacy_registration_review_missing_is_flagged() -> None:
    before, after = _observations()
    result = compare_mesh_observations(before, after, registration_evidence=_bound_evidence())
    assert "registration_operator_attribution_unavailable" in result["qc_warnings"]
    assert "registration_evidence_requires_independent_review" in result["qc_warnings"]


def test_mutated_registration_review_cannot_bypass_validation() -> None:
    before, after = _observations()
    evidence = MeshRegistrationEvidence.model_validate(_reviewed_evidence())
    evidence.independent_reviewer_id = "operator-1"
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def test_disputed_registration_review_produces_explicit_qc() -> None:
    before, after = _observations()
    evidence = _reviewed_evidence()
    evidence["independent_review_decision"] = "disputes_alignment"
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert "registration_independent_review_disputes_alignment" in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False
