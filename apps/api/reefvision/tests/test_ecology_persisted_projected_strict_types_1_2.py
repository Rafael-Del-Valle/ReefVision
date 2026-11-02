"""Fail closed on coerced ecological denominators and projected endpoint evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyCandidateReport,
    EcologyMeasurementCandidatesResponse,
    EcologyProjectedEndpointChange,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import _dated_artifact
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def test_report_denominators_reject_coerced_json_types(client: TestClient) -> None:
    original = _dated_artifact(client)
    assert original.candidate_report is not None
    report = original.candidate_report.model_dump(mode="json")
    assert EcologyCandidateReport.model_validate(report).candidate_count == 2
    fields = (
        "candidate_count",
        "source_image_count",
        "source_organism_count",
        "declared_experimental_unit_count",
        "date_qc_pass_series_count",
        "excluded_series_count",
        "excluded_source_count",
    )
    for field in fields:
        for replacement in (True, "2", 2.0, None):
            tampered = {**report, field: replacement}
            with pytest.raises(
                PydanticValidationError,
                match="report denominator must be a JSON integer",
            ):
                EcologyCandidateReport.model_validate(tampered)
            persisted = original.model_dump(mode="json")
            persisted["candidate_report"] = tampered
            with pytest.raises(
                PydanticValidationError,
                match="report denominator must be a JSON integer",
            ):
                EcologyMeasurementCandidatesResponse.model_validate(persisted)


def test_projected_endpoint_rejects_epoch_and_coerced_counts(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    endpoint = original.projected_endpoint_changes[0].model_dump(mode="json")
    assert (
        EcologyProjectedEndpointChange.model_validate(endpoint).observed_timepoint_count
        == 2
    )
    for field in ("baseline_capture_timestamp_utc", "final_capture_timestamp_utc"):
        for replacement in (
            0,
            1775217600,
            1775217600.0,
            True,
            "1775217600",
            "2026-04-03",
        ):
            tampered = {**endpoint, field: replacement}
            with pytest.raises(
                PydanticValidationError, match="requires an ISO calendar timestamp"
            ):
                EcologyProjectedEndpointChange.model_validate(tampered)
            persisted = original.model_dump(mode="json")
            persisted["projected_endpoint_changes"][0] = tampered
            with pytest.raises(
                PydanticValidationError, match="requires an ISO calendar timestamp"
            ):
                EcologyMeasurementCandidatesResponse.model_validate(persisted)

    for field in ("identity_revision", "observed_timepoint_count"):
        for replacement in (True, "2", 2.0, None):
            tampered = {**endpoint, field: replacement}
            with pytest.raises(
                PydanticValidationError, match="count/revision must be a JSON integer"
            ):
                EcologyProjectedEndpointChange.model_validate(tampered)

    offset = deepcopy(endpoint)
    offset["baseline_capture_timestamp_utc"] = "2026-04-03T04:00:00-04:00"
    offset["final_capture_timestamp_utc"] = "2026-04-05T04:00:00-04:00"
    assert EcologyProjectedEndpointChange.model_validate(offset).elapsed_days == 2
    assert EcologyProjectedEndpointChange.model_validate(
        original.projected_endpoint_changes[0].model_dump(mode="python")
    ).review_gate == "scientist_review_required"


def test_executed_saved_workflow_rejects_forged_report_count(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    standalone = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert standalone.status_code == 200, standalone.text
    executed = _workflow(client, project_id)
    assert executed["run"]["status"] == "succeeded"
    artifacts = [
        item
        for item in executed["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    assert payload == standalone.json()
    parsed = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"
    for replacement in (True, "1", 1.0):
        forged = deepcopy(payload)
        forged["candidate_report"]["source_image_count"] = replacement
        with pytest.raises(
            PydanticValidationError, match="report denominator must be a JSON integer"
        ):
            EcologyMeasurementCandidatesResponse.model_validate(forged)
