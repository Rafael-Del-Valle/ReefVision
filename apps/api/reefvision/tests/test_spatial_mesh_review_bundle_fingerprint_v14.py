"""Content-addressed, provisional review provenance for longitudinal meshes."""

from __future__ import annotations

from hashlib import sha256
from json import dumps

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request


def _observation(observation_id: str, height: int) -> dict:
    result = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                "vertices": [[0, 0, 0], [1, 0, 0], [0, height, 0]],
                "faces": [[0, 1, 2]],
                "meters_per_unit": 1,
                "calibration_method": "ruler",
                "calibration_evidence": "Unverified ruler",
                "specimen_id": "colony-1",
                "observation_id": observation_id,
                "observed_at_utc": (
                    "2026-10-01T12:00:00Z"
                    if observation_id == "early"
                    else "2026-10-02T12:00:00Z"
                ),
            }
        )
    )
    result["project_id"] = "study-1"
    return result


def _review(before: dict, after: dict) -> dict:
    return {
        "project_id": "study-1",
        "specimen_id": "colony-1",
        "before_observation_id": "early",
        "after_observation_id": "late",
        "method": "photo_match",
        "observer_id": "observer-1",
        "evidence_note": "Provisional image correspondence",
        "before_geometry_sha256": before["provenance"]["geometry_sha256"],
        "after_geometry_sha256": after["provenance"]["geometry_sha256"],
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "supports_match",
        "independent_review_note": "Reviewed but not authenticated",
        "independent_reviewed_at_utc": "2026-10-03T12:00:00Z",
    }


def test_review_fingerprint_is_canonical_and_sensitive_to_review_revision() -> None:
    before = _observation("early", 1)
    after = _observation("late", 2)
    review = _review(before, after)
    result = compare_mesh_observations(before, after, reidentification_evidence=review)
    provenance = result["provenance"]
    digest = provenance["review_evidence_bundle_sha256"]
    assert provenance["review_evidence_bundle_schema_version"] == "mesh-review-bundle-0001"
    assert isinstance(digest, str) and len(digest) == 64
    assert provenance["specimen_identity_verified"] is False
    assert provenance["reidentification_evidence_review_status"] == "caller_supplied_unverified"
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"

    # Verify the published canonical digest, not just its format.
    canonical = {
        "schema_version": "mesh-review-bundle-0001",
        "project_id": "study-1",
        "specimen_id": "colony-1",
        "before_observation_id": "early",
        "after_observation_id": "late",
        "before_observed_at_utc": "2026-10-01T12:00:00Z",
        "after_observed_at_utc": "2026-10-02T12:00:00Z",
        "before_geometry_sha256": before["provenance"]["geometry_sha256"],
        "after_geometry_sha256": after["provenance"]["geometry_sha256"],
        "registration_evidence": None,
        "reidentification_evidence": provenance["reidentification_evidence"],
    }
    expected = sha256(
        dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert digest == expected
    reversed_review = dict(reversed(list(review.items())))
    assert (
        compare_mesh_observations(
            before, after, reidentification_evidence=reversed_review
        )["provenance"]["review_evidence_bundle_sha256"]
        == digest
    )
    amended = {**review, "independent_review_note": "Second review changed interpretation"}
    assert (
        compare_mesh_observations(before, after, reidentification_evidence=amended)[
            "provenance"
        ]["review_evidence_bundle_sha256"]
        != digest
    )


def test_review_fingerprint_binds_observations_but_does_not_certify_legacy_evidence() -> None:
    before = _observation("early", 1)
    after = _observation("late", 2)
    absent = compare_mesh_observations(before, after)["provenance"]
    assert absent["review_evidence_bundle_sha256"] is None
    assert absent["review_evidence_bundle_schema_version"] is None

    review = _review(before, after)
    review.pop("before_geometry_sha256")
    review.pop("after_geometry_sha256")
    first = compare_mesh_observations(before, after, reidentification_evidence=review)
    changed = _observation("late", 3)
    second = compare_mesh_observations(before, changed, reidentification_evidence=review)
    assert (
        first["provenance"]["review_evidence_bundle_sha256"]
        != second["provenance"]["review_evidence_bundle_sha256"]
    )
    assert "reidentification_geometry_binding_unavailable" in second["qc_warnings"]
    assert second["provenance"]["specimen_identity_verified"] is False

    # A supplied geometry binding is still validated; a digest cannot excuse
    # stale evidence or turn a mismatched review into a valid measurement.
    with pytest.raises(ValueError, match="source geometry fingerprints"):
        compare_mesh_observations(
            before, changed, reidentification_evidence=_review(before, after)
        )
