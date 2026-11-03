"""Current ecological artifacts must not silently discard forged scientific claims."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyCandidateReport,
    EcologyMeasurementCandidatesResponse,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import _dated_artifact
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def test_standalone_and_executed_saved_workflow_reject_forged_claims(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    api = client.get(f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates")
    assert api.status_code == 200, api.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    saved = next(
        row["payload_json"]
        for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    )
    assert saved == api.json()

    for payload in (api.json(), saved):
        parsed = EcologyMeasurementCandidatesResponse.model_validate(payload)
        assert parsed.source_fingerprint_contract == "ecology-measurement-candidates-0021"
        assert parsed.review_gate == "scientist_review_required"
        assert parsed.evidence_level == "linked_unverified"
        for location in ("root", "candidates", "sampling_date_qc", "projected_unit_summaries"):
            altered = deepcopy(payload)
            if location == "root":
                altered["scientist_review_approved"] = True
            else:
                assert altered[location]
                altered[location][0]["scientist_review_approved"] = True
            with pytest.raises(PydanticValidationError, match="unsupported fields"):
                EcologyMeasurementCandidatesResponse.model_validate(altered)


@pytest.mark.parametrize(
    "collection",
    [
        "candidates",
        "sampling_date_qc",
        "projected_visit_coverage",
        "projected_endpoint_changes",
        "projected_unit_summaries",
        "projected_population_summaries",
    ],
)
def test_current_dated_evidence_rejects_unsupported_nested_claims(
    client: TestClient, collection: str
) -> None:
    payload = _dated_artifact(client).model_dump(mode="json")
    assert payload[collection]
    payload[collection][0]["independent_unit_registry_verified"] = True
    with pytest.raises(PydanticValidationError, match="unsupported fields"):
        EcologyMeasurementCandidatesResponse.model_validate(payload)


def test_current_exclusion_roster_cannot_carry_approval_claim(client: TestClient) -> None:
    payload = _dated_artifact(client).model_dump(mode="json")
    payload["exclusions"] = [
        {
            "calibration_evidence_id": "excluded-calibration",
            "reason": "unsupported_geometry",
            "scientist_review_approved": True,
        }
    ]
    with pytest.raises(PydanticValidationError, match="unsupported fields"):
        EcologyMeasurementCandidatesResponse.model_validate(payload)


def test_separately_persisted_candidate_report_rejects_unknown_approval(
    client: TestClient,
) -> None:
    report = _dated_artifact(client).candidate_report
    assert report is not None
    payload = report.model_dump(mode="json")
    assert EcologyCandidateReport.model_validate(payload).review_gate == "scientist_review_required"
    payload["scientist_review_approved"] = True
    with pytest.raises(PydanticValidationError, match="Extra inputs are not permitted"):
        EcologyCandidateReport.model_validate(payload)


def test_legacy_source_contract_remains_readable_without_claiming_review(
    client: TestClient,
) -> None:
    payload = _dated_artifact(client).model_dump(mode="json")
    payload["source_fingerprint_contract"] = "ecology-measurement-candidates-0020"
    payload["scientist_review_approved"] = True
    payload["candidates"][0]["independent_unit_registry_verified"] = True
    parsed = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert parsed.source_fingerprint_contract == "ecology-measurement-candidates-0020"
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"
    assert not hasattr(parsed, "scientist_review_approved")
    assert not hasattr(parsed.candidates[0], "independent_unit_registry_verified")
