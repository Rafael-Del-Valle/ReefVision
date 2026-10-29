"""Independent mesh review must not be spoofed with case-only operator aliases."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshRegistrationEvidence,
    MeshReidentificationEvidence,
)
from reefvision.tests.test_annotations import create_project


@pytest.mark.parametrize(
    ("evidence_key", "evidence", "error"),
    [
        (
            "registration_evidence",
            {
                "source_frame_id": "survey-local",
                "target_frame_id": "survey-local",
                "method": "landmark",
                "rms_residual_m": 0.02,
                "correspondence_count": 6,
                "evidence_note": "Unverified landmark alignment",
                "registration_operator_id": "Operator.A",
                "independent_reviewer_id": "operator.a",
                "independent_review_decision": "supports_alignment",
                "independent_review_note": "Independent check claimed",
            },
            "Registration reviewer must differ",
        ),
        (
            "reidentification_evidence",
            {
                "before_observation_id": "survey-1",
                "after_observation_id": "survey-2",
                "method": "photo_match",
                "observer_id": "Observer.A",
                "evidence_note": "Provisional photo match",
                "independent_reviewer_id": "observer.a",
                "independent_review_decision": "supports_match",
                "independent_review_note": "Independent check claimed",
            },
            "Independent reviewer must differ",
        ),
    ],
)
def test_case_variant_self_review_rejected_in_schema_and_standalone_api(
    client: TestClient, evidence_key: str, evidence: dict, error: str
) -> None:
    """Only a genuinely distinct reviewer may provide independent review notes."""
    schema = (
        MeshRegistrationEvidence
        if evidence_key == "registration_evidence"
        else MeshReidentificationEvidence
    )
    with pytest.raises(ValueError, match=error):
        schema.model_validate(evidence)

    project_id = str(create_project(client, "Mesh independent review QC")["id"])
    before = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field ruler",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "colony-16",
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
        "coordinate_frame_id": "survey-local",
    }
    after = {
        **before,
        "observation_id": "survey-2",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after, evidence_key: evidence},
    )
    assert response.status_code == 422, response.text
    assert error.lower() in response.text.lower()

    # A separately attributed reviewer is still accepted as provisional evidence.
    independently_attributed = {**evidence, "independent_reviewer_id": "reviewer-2"}
    assert schema.model_validate(independently_attributed).independent_reviewer_id == "reviewer-2"
