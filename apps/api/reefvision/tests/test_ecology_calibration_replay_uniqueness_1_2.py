"""Current ecological calibration links cannot masquerade as extra observations."""

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


def test_api_and_saved_workflow_allow_distinct_box_metrics_per_calibration(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == response.json()
    for payload in (response.json(), artifacts[0]["payload_json"]):
        parsed = EcologyMeasurementCandidatesResponse.model_validate(payload)
        assert parsed.source_fingerprint_contract == "ecology-measurement-candidates-0021"
        assert {row.metric for row in parsed.candidates} == {"box_width", "box_height"}
        assert len({row.calibration_evidence_id for row in parsed.candidates}) == 1
        assert parsed.review_gate == "scientist_review_required"


@pytest.mark.parametrize("source", ["api", "saved_workflow"])
def test_rehashed_duplicate_calibration_metric_cannot_inflate_observation_count(
    client: TestClient, source: str
) -> None:
    if source == "api":
        original = _dated_artifact(client)
    else:
        project_id, _ = _source(client)
        workflow = _workflow(client, project_id)
        assert workflow["run"]["status"] == "succeeded"
        payload = next(
            row["payload_json"]
            for row in workflow["artifacts"]
            if row["data_type"] == "ecology_measurement_candidates"
        )
        original = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert original.candidates
    rows = [*original.candidates, original.candidates[0]]
    forged = _resign_derived_evidence(
        original.model_copy(update={"candidates": rows, "candidate_count": len(rows)})
    )
    with pytest.raises(PydanticValidationError, match="duplicate calibration metric"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_rehashed_calibration_link_cannot_change_image_or_annotation_lineage(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    baseline, final = original.candidates
    assert baseline.metric in {"box_width", "box_height"}
    other_metric = "box_height" if baseline.metric == "box_width" else "box_width"
    forged_final = final.model_copy(
        update={
            "calibration_evidence_id": baseline.calibration_evidence_id,
            "metric": other_metric,
        }
    )
    forged = _resign_derived_evidence(
        original.model_copy(update={"candidates": [baseline, forged_final]})
    )
    with pytest.raises(PydanticValidationError, match="conflicting calibration lineage"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_historical_calibration_rows_remain_readable_but_unverified(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    historical = original.model_copy(
        update={
            "source_fingerprint_contract": "ecology-measurement-candidates-0020",
            "candidates": [*original.candidates, original.candidates[0]],
            "candidate_count": original.candidate_count + 1,
        }
    )
    parsed = EcologyMeasurementCandidatesResponse.model_validate(historical.model_dump(mode="json"))
    assert parsed.candidate_count == 3
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"
