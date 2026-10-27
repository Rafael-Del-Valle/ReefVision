"""Registration evidence must track calibration provenance revisions independently of scale."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshPreviewRequest,
    MeshRegistrationEvidence,
    MeshReidentificationEvidence,
)
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
            "meters_per_mesh_unit": 1.0,
            "relative_scale_uncertainty": 0.1,
            "calibration_method": "ruler",
            "calibration_evidence": "Ruler reference photo 01",
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
        "evidence_note": "Provisional alignment; not independently verified",
        "source_geometry_sha256": "a" * 64,
        "target_geometry_sha256": "b" * 64,
        "source_meters_per_mesh_unit": 1.0,
        "target_meters_per_mesh_unit": 1.0,
        "source_relative_scale_uncertainty": 0.1,
        "target_relative_scale_uncertainty": 0.1,
        "source_calibration_method": "ruler",
        "target_calibration_method": "ruler",
        "source_calibration_evidence": "Ruler reference photo 01",
        "target_calibration_evidence": "Ruler reference photo 01",
    }


def test_calibration_provenance_bound_registration_remains_unverified() -> None:
    before, after = _observations()
    evidence = _evidence()
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert result["provenance"]["registration_evidence"] == evidence
    assert "registration_calibration_provenance_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("timepoint", "field", "revision"),
    [
        ("source", "calibration_method", "instrument"),
        ("target", "calibration_method", "photogrammetry_control"),
        ("source", "calibration_evidence", "Revised ruler reference photo 02"),
        ("target", "calibration_evidence", "Revised ruler reference photo 02"),
    ],
)
def test_registration_rejects_revised_calibration_with_unchanged_geometry_and_scale(
    timepoint: str, field: str, revision: str
) -> None:
    before, after = _observations()
    observation = before if timepoint == "source" else after
    observation["provenance"][field] = revision
    with pytest.raises(ValueError, match="both calibration provenance records"):
        compare_mesh_observations(before, after, registration_evidence=_evidence())


@pytest.mark.parametrize(
    "missing",
    [
        "source_calibration_method",
        "target_calibration_method",
        "source_calibration_evidence",
        "target_calibration_evidence",
    ],
)
def test_incomplete_calibration_provenance_binding_is_rejected(missing: str) -> None:
    evidence = _evidence()
    del evidence[missing]
    with pytest.raises(PydanticValidationError, match="requires all four fields"):
        MeshRegistrationEvidence.model_validate(evidence)


def test_malformed_calibration_method_and_empty_evidence_are_rejected() -> None:
    evidence = _evidence()
    evidence["source_calibration_method"] = "not-a-calibration-method"
    with pytest.raises(PydanticValidationError):
        MeshRegistrationEvidence.model_validate(evidence)
    evidence = _evidence()
    evidence["target_calibration_evidence"] = ""
    with pytest.raises(PydanticValidationError):
        MeshRegistrationEvidence.model_validate(evidence)



@pytest.mark.parametrize(
    "field",
    [
        "evidence_note",
        "source_calibration_evidence",
        "target_calibration_evidence",
        "independent_review_note",
    ],
)
def test_registration_rejects_whitespace_only_audit_evidence(field: str) -> None:
    evidence = _evidence()
    if field == "independent_review_note":
        evidence.update(
            registration_operator_id="operator-1",
            independent_reviewer_id="reviewer-2",
            independent_review_decision="supports_alignment",
        )
    evidence[field] = " \t "
    with pytest.raises(PydanticValidationError, match="cannot be blank"):
        MeshRegistrationEvidence.model_validate(evidence)
    before, after = _observations()
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


def test_mutated_registration_note_is_revalidated_before_comparison() -> None:
    before, after = _observations()
    evidence = MeshRegistrationEvidence.model_validate(_evidence())
    evidence.evidence_note = " \t "
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)


@pytest.mark.parametrize("field", ["evidence_note", "independent_review_note"])
def test_reidentification_rejects_whitespace_only_audit_evidence(field: str) -> None:
    evidence = {
        "before_observation_id": "scan-1",
        "after_observation_id": "scan-2",
        "method": "visual_morphology",
        "observer_id": "observer-1",
        "evidence_note": "Unverified visual morphology",
    }
    if field == "independent_review_note":
        evidence.update(
            independent_reviewer_id="reviewer-2",
            independent_review_decision="supports_match",
        )
    evidence[field] = " \t "
    with pytest.raises(PydanticValidationError, match="cannot be blank"):
        MeshReidentificationEvidence.model_validate(evidence)


def test_preview_rejects_whitespace_only_calibration_evidence() -> None:
    with pytest.raises(PydanticValidationError, match="cannot be blank"):
        MeshPreviewRequest.model_validate(
            {
                "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                "faces": [[0, 1, 2]],
                "meters_per_unit": 1.0,
                "calibration_method": "ruler",
                "calibration_evidence": " \t ",
            }
        )


def test_legacy_registration_without_provenance_binding_is_flagged() -> None:
    before, after = _observations()
    evidence = _evidence()
    for key in (
        "source_calibration_method",
        "target_calibration_method",
        "source_calibration_evidence",
        "target_calibration_evidence",
    ):
        del evidence[key]
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    assert "registration_calibration_provenance_binding_unavailable" in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


def test_mutated_calibration_provenance_model_is_revalidated() -> None:
    before, after = _observations()
    evidence = MeshRegistrationEvidence.model_validate(_evidence())
    evidence.target_calibration_evidence = "New reference after review"
    with pytest.raises(ValueError, match="both calibration provenance records"):
        compare_mesh_observations(before, after, registration_evidence=evidence)
    evidence.target_calibration_evidence = None
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, registration_evidence=evidence)
