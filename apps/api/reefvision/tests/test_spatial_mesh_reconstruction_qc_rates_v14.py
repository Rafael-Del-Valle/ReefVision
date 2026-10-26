"""Descriptive mesh reconstruction QC rates are not biological condition estimates."""

from __future__ import annotations

from copy import deepcopy

import pytest

from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations


def _observations() -> tuple[dict, dict]:
    before = {
        "project_id": "study-1",
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "face_count": 10,
        "edge_connected_patch_count": 1,
        "boundary_edge_count": 6,
        "nonmanifold_edge_count": 2,
        "degenerate_face_count": 1,
        "provenance": {
            "specimen_id": "coral-1",
            "observation_id": "survey-1",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = deepcopy(before)
    after["provenance"]["observation_id"] = "survey-2"
    after["provenance"]["observed_at_utc"] = "2026-10-02T12:00:00Z"
    after.update(
        face_count=20,
        boundary_edge_count=2,
        nonmanifold_edge_count=0,
        degenerate_face_count=0,
    )
    return before, after


def test_reconstruction_qc_rates_normalize_counts_without_claiming_condition() -> None:
    before, after = _observations()
    result = compare_mesh_observations(before, after)
    assert result["before_reconstruction_qc_rates"] == pytest.approx(
        {
            "degenerate_face_fraction": 0.1,
            "boundary_edges_per_face": 0.6,
            "nonmanifold_edges_per_face": 0.2,
        }
    )
    assert result["after_reconstruction_qc_rates"] == pytest.approx(
        {
            "degenerate_face_fraction": 0.0,
            "boundary_edges_per_face": 0.1,
            "nonmanifold_edges_per_face": 0.0,
        }
    )
    assert result["reconstruction_qc_rate_changes_after_minus_before"] == pytest.approx(
        {
            "degenerate_face_fraction": -0.1,
            "boundary_edges_per_face": -0.5,
            "nonmanifold_edges_per_face": -0.2,
        }
    )
    assert "reconstruction_qc_rates_not_biological_condition" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_missing_topology_does_not_imply_zero_defects() -> None:
    before, after = _observations()
    before.pop("boundary_edge_count")
    result = compare_mesh_observations(before, after)
    assert result["before_reconstruction_qc_rates"]["boundary_edges_per_face"] is None
    assert result["after_reconstruction_qc_rates"]["boundary_edges_per_face"] == 0.1
    assert (
        result["reconstruction_qc_rate_changes_after_minus_before"]["boundary_edges_per_face"]
        is None
    )
    assert "reconstruction_topology_comparison_incomplete" in result["qc_warnings"]


def test_zero_triangle_reconstructions_have_unavailable_rates() -> None:
    before, after = _observations()
    for observation in (before, after):
        observation.update(
            face_count=0,
            edge_connected_patch_count=0,
            boundary_edge_count=0,
            nonmanifold_edge_count=0,
            degenerate_face_count=0,
        )
    result = compare_mesh_observations(before, after)
    assert all(value is None for value in result["before_reconstruction_qc_rates"].values())
    assert all(value is None for value in result["after_reconstruction_qc_rates"].values())
    assert "reconstruction_qc_rates_unavailable" in result["qc_warnings"]



def test_zero_face_baseline_preserves_missing_rates_against_valid_followup() -> None:
    before, after = _observations()
    before.update(
        face_count=0,
        edge_connected_patch_count=0,
        boundary_edge_count=0,
        nonmanifold_edge_count=0,
        degenerate_face_count=0,
    )
    result = compare_mesh_observations(before, after)
    assert all(value is None for value in result["before_reconstruction_qc_rates"].values())
    assert result["after_reconstruction_qc_rates"] == pytest.approx(
        {
            "degenerate_face_fraction": 0.0,
            "boundary_edges_per_face": 0.1,
            "nonmanifold_edges_per_face": 0.0,
        }
    )
    assert all(
        value is None
        for value in result["reconstruction_qc_rate_changes_after_minus_before"].values()
    )
    assert "reconstruction_topology_changed_requires_review" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False

def test_invalid_boolean_face_count_is_rejected() -> None:
    before, after = _observations()
    before["face_count"] = True
    with pytest.raises(ValueError, match="face_count"):
        compare_mesh_observations(before, after)
