"""Reidentification evidence must remain bound to both reconstructed meshes."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.spatial_mesh_preview_v14 import MeshReidentificationEvidence
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations


def _observations() -> tuple[dict, dict]:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "project_id": "local-study",
        "surface_area_m2": 1.0,
        "provenance": {
            "specimen_id": "coral-1",
            "observation_id": "before",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "a" * 64,
        },
    }
    after = deepcopy(before)
    after["provenance"]["observation_id"] = "after"
    after["provenance"]["observed_at_utc"] = "2026-10-02T12:00:00Z"
    after["provenance"]["geometry_sha256"] = "b" * 64
    return before, after


def _evidence() -> dict:
    return {
        "project_id": "local-study",
        "specimen_id": "coral-1",
        "before_observation_id": "before",
        "after_observation_id": "after",
        "method": "photo_match",
        "observer_id": "annotator-1",
        "evidence_note": "Provisional image correspondence; not independently reviewed",
        "before_geometry_sha256": "a" * 64,
        "after_geometry_sha256": "b" * 64,
    }


def test_bound_reidentification_is_preserved_but_not_verified() -> None:
    before, after = _observations()
    evidence = _evidence()
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert result["provenance"]["reidentification_evidence"] == evidence
    assert "reidentification_geometry_binding_unavailable" not in result["qc_warnings"]
    assert "reidentification_evidence_requires_independent_review" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


@pytest.mark.parametrize("changed_observation", ["before", "after"])
def test_reidentification_cannot_be_reused_for_other_geometry(
    changed_observation: str,
) -> None:
    before, after = _observations()
    record = before if changed_observation == "before" else after
    record["provenance"]["geometry_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="source geometry fingerprints"):
        compare_mesh_observations(before, after, reidentification_evidence=_evidence())


def test_legacy_unbound_reidentification_is_flagged_not_certified() -> None:
    before, after = _observations()
    evidence = _evidence()
    del evidence["before_geometry_sha256"]
    del evidence["after_geometry_sha256"]
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert "reidentification_geometry_binding_unavailable" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_partial_or_malformed_geometry_binding_is_rejected() -> None:
    evidence = _evidence()
    del evidence["after_geometry_sha256"]
    with pytest.raises(PydanticValidationError, match="requires both"):
        MeshReidentificationEvidence.model_validate(evidence)
    evidence["after_geometry_sha256"] = "NOT-A-SHA256"
    with pytest.raises(PydanticValidationError):
        MeshReidentificationEvidence.model_validate(evidence)


def test_mutated_evidence_model_is_revalidated_before_comparison() -> None:
    before, after = _observations()
    evidence = MeshReidentificationEvidence.model_validate(_evidence())
    evidence.after_geometry_sha256 = "c" * 64
    with pytest.raises(ValueError, match="source geometry fingerprints"):
        compare_mesh_observations(before, after, reidentification_evidence=evidence)


def test_reidentification_timepoint_binding_accepts_equivalent_offsets() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence["before_observed_at_utc"] = "2026-10-01T07:00:00-05:00"
    evidence["after_observed_at_utc"] = "2026-10-02T12:00:00Z"
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert "reidentification_timepoint_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["reidentification_evidence"]["before_observed_at_utc"]
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize("changed_observation", ["before", "after"])
def test_reidentification_cannot_be_reused_for_other_timepoint(
    changed_observation: str,
) -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence["before_observed_at_utc"] = "2026-10-01T12:00:00Z"
    evidence["after_observed_at_utc"] = "2026-10-02T12:00:00Z"
    record = before if changed_observation == "before" else after
    record["provenance"]["observed_at_utc"] = (
        "2026-10-01T13:00:00Z" if changed_observation == "before" else "2026-10-02T13:00:00Z"
    )
    with pytest.raises(ValueError, match="observation timestamps"):
        compare_mesh_observations(before, after, reidentification_evidence=evidence)


def test_partial_or_naive_timepoint_binding_is_rejected() -> None:
    evidence = _evidence()
    evidence["before_observed_at_utc"] = "2026-10-01T12:00:00Z"
    with pytest.raises(PydanticValidationError, match="requires both UTC timestamps"):
        MeshReidentificationEvidence.model_validate(evidence)
    evidence["after_observed_at_utc"] = "2026-10-02T12:00:00"
    with pytest.raises(PydanticValidationError):
        MeshReidentificationEvidence.model_validate(evidence)


def test_legacy_reidentification_without_timepoint_binding_is_flagged() -> None:
    before, after = _observations()
    result = compare_mesh_observations(before, after, reidentification_evidence=_evidence())
    assert "reidentification_timepoint_binding_unavailable" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_independent_reviewer_disagreement_remains_provisional() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="disputes_match",
        independent_review_note="Source photos do not show the same branch junction",
    )
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    warnings = result["qc_warnings"]
    assert "reidentification_independent_review_disputes_match" in warnings
    assert "reidentification_independent_review_recorded_not_identity_verification" in warnings
    assert "reidentification_evidence_requires_independent_review" not in warnings
    assert result["provenance"]["reidentification_evidence"] == evidence
    assert result["provenance"]["reidentification_evidence_review_status"] == (
        "caller_supplied_unverified"
    )
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


@pytest.mark.parametrize(
    "missing_field",
    ["independent_reviewer_id", "independent_review_decision", "independent_review_note"],
)
def test_incomplete_independent_review_is_rejected(missing_field: str) -> None:
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="supports_match",
        independent_review_note="Independent comparison of source photographs",
    )
    del evidence[missing_field]
    with pytest.raises(PydanticValidationError, match="requires reviewer, decision, and note"):
        MeshReidentificationEvidence.model_validate(evidence)


def test_matching_observer_cannot_claim_independent_review() -> None:
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="annotator-1",
        independent_review_decision="supports_match",
        independent_review_note="Self-review cannot be independent",
    )
    with pytest.raises(PydanticValidationError, match="must differ from matching observer"):
        MeshReidentificationEvidence.model_validate(evidence)


def test_mutated_independent_review_is_revalidated_before_comparison() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="inconclusive",
        independent_review_note="Incomplete survey photos",
    )
    model = MeshReidentificationEvidence.model_validate(evidence)
    model.independent_reviewer_id = model.observer_id
    with pytest.raises(ValueError, match="Invalid pairwise reidentification evidence"):
        compare_mesh_observations(before, after, reidentification_evidence=model)


def test_independent_review_timestamp_is_preserved_without_identity_certification() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="supports_match",
        independent_review_note="Reviewed after the second survey",
        independent_reviewed_at_utc="2026-10-02T08:00:00-05:00",
    )
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert "reidentification_independent_review_timestamp_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["reidentification_evidence"]["independent_reviewed_at_utc"]
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize(
    "reviewed_at",
    ["2026-10-02T11:59:59Z", "2026-10-02T06:59:59-05:00"],
)
def test_independent_review_cannot_predate_followup_survey(reviewed_at: str) -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="supports_match",
        independent_review_note="Timestamp precedes the survey",
        independent_reviewed_at_utc=reviewed_at,
    )
    with pytest.raises(ValueError, match="predates the later observation"):
        compare_mesh_observations(before, after, reidentification_evidence=evidence)


def test_legacy_undated_independent_review_remains_provisional_with_qc() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="inconclusive",
        independent_review_note="Historical review without a timestamp",
    )
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert "reidentification_independent_review_timestamp_unavailable" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_dated_review_without_reviewer_or_timezone_is_rejected() -> None:
    evidence = _evidence()
    evidence["independent_reviewed_at_utc"] = "2026-10-03T12:00:00Z"
    with pytest.raises(PydanticValidationError, match="requires a separately attributed reviewer"):
        MeshReidentificationEvidence.model_validate(evidence)
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="supports_match",
        independent_review_note="Dated review",
        independent_reviewed_at_utc="2026-10-03T12:00:00",
    )
    with pytest.raises(PydanticValidationError):
        MeshReidentificationEvidence.model_validate(evidence)


def test_mutated_review_timestamp_is_rechecked_at_execution() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence.update(
        independent_reviewer_id="reviewer-2",
        independent_review_decision="supports_match",
        independent_review_note="Valid when recorded",
        independent_reviewed_at_utc="2026-10-03T12:00:00Z",
    )
    model = MeshReidentificationEvidence.model_validate(evidence)
    model.independent_reviewed_at_utc = datetime(2026, 10, 1, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="predates the later observation"):
        compare_mesh_observations(before, after, reidentification_evidence=model)


def test_project_bound_reidentification_cannot_cross_projects() -> None:
    before, after = _observations()
    before["project_id"] = "other-project"
    after["project_id"] = "other-project"
    with pytest.raises(ValueError, match="must match the project ID"):
        compare_mesh_observations(before, after, reidentification_evidence=_evidence())


def test_project_binding_rejects_wrong_project_even_with_same_observation_ids() -> None:
    before, after = _observations()
    evidence = _evidence()
    evidence["project_id"] = "other-project"
    with pytest.raises(ValueError, match="must match the project ID"):
        compare_mesh_observations(before, after, reidentification_evidence=evidence)


def test_legacy_unbound_project_evidence_is_flagged_not_certified() -> None:
    before, after = _observations()
    evidence = _evidence()
    del evidence["project_id"]
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert "reidentification_project_binding_unavailable" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_bound_project_evidence_remains_provisional() -> None:
    before, after = _observations()
    result = compare_mesh_observations(before, after, reidentification_evidence=_evidence())
    assert "reidentification_project_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["reidentification_evidence"]["project_id"] == "local-study"
    assert result["provenance"]["specimen_identity_verified"] is False


def test_invalid_or_mutated_project_binding_is_rejected() -> None:
    evidence = _evidence()
    evidence["project_id"] = ""
    with pytest.raises(PydanticValidationError):
        MeshReidentificationEvidence.model_validate(evidence)
    evidence["project_id"] = "local-study"
    model = MeshReidentificationEvidence.model_validate(evidence)
    model.project_id = "other-project"
    before, after = _observations()
    with pytest.raises(ValueError, match="must match the project ID"):
        compare_mesh_observations(before, after, reidentification_evidence=model)

