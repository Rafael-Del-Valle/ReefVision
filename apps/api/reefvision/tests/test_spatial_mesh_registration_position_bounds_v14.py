"""Provisional, caller-bounded 3D centroid separation diagnostics."""

from __future__ import annotations

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshRegistrationEvidence
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations


def _observation(observation_id: str, observed_at: str, x: float) -> dict:
    return {
        "project_id": "study-1",
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "area_weighted_surface_centroid_m": [x, 0.0, 0.0],
        "provenance": {
            "specimen_id": "coral-1",
            "observation_id": observation_id,
            "observed_at_utc": observed_at,
            "calibration_verified": False,
            "coordinate_frame_id": "survey-frame",
        },
    }


def _registration() -> dict:
    return {
        "source_frame_id": "survey-frame",
        "target_frame_id": "survey-frame",
        "method": "landmark",
        "rms_residual_m": 0.02,
        "correspondence_count": 6,
        "evidence_note": "Caller-supplied, independent verification pending",
        "source_to_target_transform_m": [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
    }


def _compare(evidence: MeshRegistrationEvidence | dict) -> dict:
    return compare_mesh_observations(
        _observation("before", "2026-10-01T12:00:00Z", 0.0),
        _observation("after", "2026-10-02T12:00:00Z", 1.0),
        registration_evidence=evidence,
    )


def test_complete_caller_bounds_produce_conservative_unverified_interval() -> None:
    evidence = {
        **_registration(),
        "source_centroid_position_error_bound_m": 0.1,
        "target_centroid_position_error_bound_m": 0.2,
        "registration_alignment_error_bound_m": 0.05,
    }
    result = _compare(evidence)
    assert result["registered_surface_centroid_separation_m"] == pytest.approx(1.0)
    assert result["registered_surface_centroid_separation_caller_bound_interval_m"] == (
        pytest.approx([0.65, 1.35])
    )
    assert "registered_centroid_caller_bounds_not_independently_verified" in result["qc_warnings"]
    assert "registered_centroid_caller_interval_not_a_confidence_interval" in result["qc_warnings"]
    assert result["provenance"]["registration_evidence"] == evidence
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_missing_caller_bounds_never_infers_interval_from_rms() -> None:
    result = _compare(_registration())
    assert result["registered_surface_centroid_separation_m"] == pytest.approx(1.0)
    assert result["registered_surface_centroid_separation_caller_bound_interval_m"] is None
    assert (
        result["registered_surface_centroid_offset_target_frame_caller_bound_intervals_m"] is None
    )
    assert "registered_centroid_error_bounds_unavailable" in result["qc_warnings"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"source_centroid_position_error_bound_m": 0.1},
        {
            "source_centroid_position_error_bound_m": 0.1,
            "target_centroid_position_error_bound_m": 0.2,
        },
    ],
)
def test_partial_caller_bounds_are_rejected(invalid: dict) -> None:
    with pytest.raises(ValueError, match="all three error bounds"):
        _compare({**_registration(), **invalid})


def test_error_bounds_require_registration_transform() -> None:
    evidence = _registration()
    evidence.pop("source_to_target_transform_m")
    evidence.update(
        source_centroid_position_error_bound_m=0.1,
        target_centroid_position_error_bound_m=0.2,
        registration_alignment_error_bound_m=0.05,
    )
    with pytest.raises(ValueError, match="require a transform"):
        _compare(evidence)


@pytest.mark.parametrize("bad_bound", [float("nan"), -1.0, True, "0.1"])
def test_nonfinite_negative_and_nonnumeric_bounds_are_rejected(bad_bound: object) -> None:
    evidence = {
        **_registration(),
        "source_centroid_position_error_bound_m": bad_bound,
        "target_centroid_position_error_bound_m": 0.2,
        "registration_alignment_error_bound_m": 0.05,
    }
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        _compare(evidence)


def test_mutated_existing_evidence_is_revalidated_before_comparison() -> None:
    evidence = MeshRegistrationEvidence.model_validate(
        {
            **_registration(),
            "source_centroid_position_error_bound_m": 0.1,
            "target_centroid_position_error_bound_m": 0.2,
            "registration_alignment_error_bound_m": 0.05,
        }
    )
    evidence.target_centroid_position_error_bound_m = -0.2
    with pytest.raises(ValueError, match="Invalid pairwise registration evidence"):
        _compare(evidence)


@pytest.mark.parametrize("separation", [0.0, 1.0])
def test_signed_centroid_component_intervals_bound_each_axis(separation: float) -> None:
    """Euclidean radii bound signed components, not just scalar separation."""
    evidence = {
        **_registration(),
        "source_centroid_position_error_bound_m": 0.1,
        "target_centroid_position_error_bound_m": 0.2,
        "registration_alignment_error_bound_m": 0.05,
    }
    before = _observation("before", "2026-10-01T12:00:00Z", 0.0)
    after = _observation("after", "2026-10-02T12:00:00Z", separation)
    result = compare_mesh_observations(before, after, registration_evidence=evidence)
    intervals = result["registered_surface_centroid_offset_target_frame_caller_bound_intervals_m"]
    assert intervals is not None
    for observed, expected in zip(
        intervals,
        [[separation - 0.35, separation + 0.35], [-0.35, 0.35], [-0.35, 0.35]],
        strict=True,
    ):
        assert observed == pytest.approx(expected)
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"
    assert result["provenance"]["coordinate_registration_verified"] is False
