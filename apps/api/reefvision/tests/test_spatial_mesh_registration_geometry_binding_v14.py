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
