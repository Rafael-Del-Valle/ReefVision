"""One frozen annotation evidence link cannot manufacture multiple calibrations.

A box may legitimately supply width and height from one calibration link.
Distinct calibration evidence IDs for that same annotation are impossible in
the project registry and must fail even if a saved artifact is re-signed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import (
    _dated_artifact,
    _resign_derived_evidence,
)
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


@pytest.mark.parametrize("source", ["standalone", "saved_workflow"])
def test_rehashed_annotation_link_cannot_claim_two_calibrations(
    client: TestClient, source: str
) -> None:
    project_id, _ = _source(client)
    if source == "standalone":
        response = client.get(
            f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
    else:
        executed = _workflow(client, project_id)
        assert executed["run"]["status"] == "succeeded"
        artifacts = [
            row
            for row in executed["artifacts"]
            if row["data_type"] == "ecology_measurement_candidates"
        ]
        assert len(artifacts) == 1
        payload = artifacts[0]["payload_json"]

    original = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert original.source_fingerprint_contract == "ecology-measurement-candidates-0021"
    assert {row.metric for row in original.candidates} == {"box_width", "box_height"}
    assert len({row.annotation_evidence_id for row in original.candidates}) == 1
    assert len({row.calibration_evidence_id for row in original.candidates}) == 1
    assert original.evidence_level == "linked_unverified"
    assert original.review_gate == "scientist_review_required"

    forged_second = original.candidates[1].model_copy(
        update={"calibration_evidence_id": "invented-calibration-link"}
    )
    forged = _resign_derived_evidence(
        original.model_copy(update={"candidates": [original.candidates[0], forged_second]})
    )
    with pytest.raises(
        PydanticValidationError, match="conflicting annotation calibration lineage"
    ):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_rehashed_two_date_series_cannot_reuse_one_annotation_link(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    assert len(original.candidates) == 2
    parsed = EcologyMeasurementCandidatesResponse.model_validate(
        original.model_dump(mode="json")
    )
    assert parsed.review_gate == "scientist_review_required"
    baseline, final = original.candidates
    assert baseline.calibration_evidence_id != final.calibration_evidence_id
    forged_final = final.model_copy(
        update={"annotation_evidence_id": baseline.annotation_evidence_id}
    )
    forged = _resign_derived_evidence(
        original.model_copy(update={"candidates": [baseline, forged_final]})
    )
    with pytest.raises(
        PydanticValidationError, match="conflicting annotation calibration lineage"
    ):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))
