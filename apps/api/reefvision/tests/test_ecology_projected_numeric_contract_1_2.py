"""Persisted projected ecology must not coerce counts or measured numbers.

Source-linked results remain unverified and require scientist review. Numeric
coercion would make an altered saved artifact look like an authentic result.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
    EcologyProjectedEndpointChange,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import _dated_artifact
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


@pytest.mark.parametrize(
    ("section", "field", "replacement", "message"),
    [
        ("sampling_date_qc", "candidate_count", True, "QC count"),
        ("sampling_date_qc", "candidate_count", 2.0, "QC count"),
        ("projected_visit_coverage", "linked_measurement_count", "1", "visit count"),
        ("projected_visit_coverage", "linked_measurement_count", True, "visit count"),
        ("projected_endpoint_changes", "baseline_value", "1", "endpoint numeric"),
        ("projected_endpoint_changes", "final_value", True, "endpoint numeric"),
        ("projected_endpoint_changes", "absolute_change", "2", "endpoint numeric"),
        ("projected_endpoint_changes", "percent_change", True, "endpoint numeric"),
        ("projected_endpoint_changes", "elapsed_days", "2", "endpoint numeric"),
        (
            "projected_endpoint_changes",
            "projected_absolute_change_per_day",
            "1",
            "endpoint numeric",
        ),
        (
            "projected_endpoint_changes",
            "projected_baseline_percent_change_per_day",
            True,
            "endpoint numeric",
        ),
        ("projected_unit_summaries", "mean_absolute_change", "2", "unit mean"),
        ("projected_unit_summaries", "mean_percent_change", True, "unit mean"),
        ("projected_population_summaries", "declared_unit_count", 1.0, "population count"),
        (
            "projected_population_summaries",
            "contributing_organism_count",
            "1",
            "population count",
        ),
        (
            "projected_population_summaries",
            "mean_unit_absolute_change",
            "2",
            "population statistic",
        ),
        (
            "projected_population_summaries",
            "mean_unit_percent_change",
            True,
            "population statistic",
        ),
        (
            "projected_population_summaries",
            "sample_sd_unit_absolute_change",
            "0.0",
            "population statistic",
        ),
        (
            "projected_population_summaries",
            "sample_sd_unit_percent_change",
            True,
            "population statistic",
        ),
    ],
)
def test_projected_scientific_artifact_rejects_coerced_json_evidence(
    client: TestClient,
    section: str,
    field: str,
    replacement: object,
    message: str,
) -> None:
    original = _dated_artifact(client).model_dump(mode="json")
    assert EcologyMeasurementCandidatesResponse.model_validate(original).review_gate == (
        "scientist_review_required"
    )
    assert original[section]
    tampered = deepcopy(original)
    tampered[section][0][field] = replacement
    with pytest.raises(PydanticValidationError, match=message):
        EcologyMeasurementCandidatesResponse.model_validate(tampered)


def test_standalone_endpoint_numbers_preserve_real_numeric_types(client: TestClient) -> None:
    original = _dated_artifact(client)
    endpoint = original.projected_endpoint_changes[0].model_dump(mode="json")
    parsed = EcologyProjectedEndpointChange.model_validate(endpoint)
    assert parsed.elapsed_days > 0
    assert parsed.review_gate == "scientist_review_required"
    for replacement in ("1.0", True, None, []):
        tampered = {**endpoint, "baseline_value": replacement}
        with pytest.raises(PydanticValidationError):
            EcologyProjectedEndpointChange.model_validate(tampered)


def test_executed_saved_workflow_source_count_rejects_coerced_json(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    executed = _workflow(client, project_id)
    assert executed["run"]["status"] == "succeeded"
    artifacts = [
        row
        for row in executed["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    assert payload == response.json()
    original = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert original.candidate_count == len(original.candidates)
    assert original.evidence_level == "linked_unverified"
    assert original.review_gate == "scientist_review_required"
    for replacement in (True, "2", 2.0):
        forged = deepcopy(payload)
        forged["candidate_count"] = replacement
        with pytest.raises(PydanticValidationError, match="candidate count"):
            EcologyMeasurementCandidatesResponse.model_validate(forged)
