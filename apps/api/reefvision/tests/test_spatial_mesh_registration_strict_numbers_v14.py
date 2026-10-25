"""Regression guards for unverified registration evidence numeric coercion."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.spatial_mesh_preview_v14 import MeshRegistrationEvidence
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations


def _evidence() -> dict:
    return {
        "source_frame_id": "survey-a",
        "target_frame_id": "survey-b",
        "method": "landmark",
        "rms_residual_m": 0.02,
        "correspondence_count": 6,
        "evidence_note": "Caller supplied; independent review pending",
        "source_to_target_transform_m": [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ],
    }


def _observation(observation_id: str, timestamp: str, frame: str) -> dict:
    return {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "project_id": "project-1",
        "surface_area_m2": 1.0,
        "provenance": {
            "specimen_id": "coral-1",
            "observation_id": observation_id,
            "observed_at_utc": timestamp,
            "calibration_verified": False,
            "coordinate_frame_id": frame,
        },
    }


@pytest.mark.parametrize(
    "invalid_entry",
    [
        "rms_string",
        "rms_boolean",
        "matrix_string",
        "matrix_boolean",
    ],
)
def test_registration_rejects_coerced_numbers_in_standalone_comparison(
    invalid_entry: str,
) -> None:
    evidence = _evidence()
    if invalid_entry == "rms_string":
        evidence["rms_residual_m"] = "0.02"
    elif invalid_entry == "rms_boolean":
        evidence["rms_residual_m"] = True
    elif invalid_entry == "matrix_string":
        evidence["source_to_target_transform_m"][0][0] = "1"
    else:
        evidence["source_to_target_transform_m"][0][0] = True

    with pytest.raises(PydanticValidationError):
        MeshRegistrationEvidence.model_validate(evidence)

    before = _observation("scan-1", "2026-10-01T12:00:00Z", "survey-a")
    after = _observation("scan-2", "2026-10-02T12:00:00Z", "survey-b")
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        compare_mesh_observations(before, after, evidence)


def test_registration_accepts_integer_matrix_as_unverified() -> None:
    evidence = _evidence()
    evidence["rms_residual_m"] = 0
    validated = MeshRegistrationEvidence.model_validate(evidence)
    assert validated.rms_residual_m == 0.0
    assert validated.source_to_target_transform_m == evidence["source_to_target_transform_m"]

    before = _observation("scan-1", "2026-10-01T12:00:00Z", "survey-a")
    after = _observation("scan-2", "2026-10-02T12:00:00Z", "survey-b")
    result = compare_mesh_observations(before, after, evidence)
    assert result["provenance"]["registration_evidence"]["rms_residual_m"] == 0.0
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert "registration_transform_requires_independent_review" in result["qc_warnings"]
