"""Reidentification evidence must remain bound to both reconstructed meshes."""

from __future__ import annotations

from copy import deepcopy

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
    record["provenance"]["observed_at_utc"] = "2026-10-03T12:00:00Z"
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
