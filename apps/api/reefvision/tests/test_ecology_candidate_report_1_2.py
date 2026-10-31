"""Reproducible ecological QC report: API, CSV and saved Workflow Builder parity."""

from __future__ import annotations

import csv
from copy import deepcopy
from io import StringIO

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyCandidateReport,
    EcologyMeasurementCandidatesResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def test_ecological_qc_report_matches_api_csv_and_saved_workflow(client: TestClient) -> None:
    project_id, source = _source(client)
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    response = client.get(path)
    assert response.status_code == 200, response.text
    payload = response.json()
    report = payload["candidate_report"]
    assert report["candidate_count"] == payload["candidate_count"]
    assert report["source_image_count"] == 1
    assert report["source_organism_count"] == 1
    assert report["source_input_sha256"] == payload["input_sha256"]
    assert report["evidence_level"] == "linked_unverified"
    assert report["review_gate"] == "scientist_review_required"
    assert source.image_id in [row["image_id"] for row in payload["candidates"]]
    assert report["qc_status_counts"] == {"missing_timestamps": 2}

    csv_response = client.get(path + "/report.csv")
    assert csv_response.status_code == 200, csv_response.text
    rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert rows[0]["report_sha256"] == report["report_sha256"]
    assert rows[0]["review_gate"] == "scientist_review_required"
    assert rows[0]["qc_status"] == "missing_timestamps"

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(
        row for row in registry.json() if row["node_type"] == "ecology_identity_registry_source"
    )
    assert any(
        port["port_id"] == "candidate_report"
        and port["accepted_types"] == ["ecology_candidate_report"]
        for port in node["output_ports"]
    )
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_candidate_report"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == report

    legacy = dict(payload)
    legacy.pop("candidate_report")
    assert EcologyMeasurementCandidatesResponse.model_validate(legacy).candidate_report is None


def test_saved_ecological_report_rejects_tampered_or_rehashed_source_counts(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    response = client.get(path)
    assert response.status_code == 200, response.text
    payload = response.json()
    report = payload["candidate_report"]
    assert EcologyMeasurementCandidatesResponse.model_validate(payload).candidate_report
    assert EcologyCandidateReport.model_validate(report).report_sha256 == report["report_sha256"]

    # A separately persisted executable Workflow Builder report port must
    # deserialize under the same signed, unverified scientific contract.
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    report_artifacts = [
        row
        for row in workflow["artifacts"]
        if row["data_type"] == "ecology_candidate_report"
    ]
    assert len(report_artifacts) == 1
    assert report_artifacts[0]["payload_json"] == report
    EcologyCandidateReport.model_validate(report_artifacts[0]["payload_json"])

    # Edits without a matching digest are rejected even when they leave the
    # source-candidate fingerprint and workflow lineage strings untouched.
    for field in (
        "candidate_count",
        "source_image_count",
        "source_organism_count",
        "declared_experimental_unit_count",
        "date_qc_pass_series_count",
        "excluded_series_count",
        "excluded_source_count",
    ):
        altered = deepcopy(payload)
        altered["candidate_report"][field] += 1
        with pytest.raises(PydanticValidationError, match="report fingerprint"):
            EcologyMeasurementCandidatesResponse.model_validate(altered)
        with pytest.raises(PydanticValidationError, match="report fingerprint"):
            EcologyCandidateReport.model_validate(altered["candidate_report"])

    # Rehashing a fabricated report is insufficient: the typed candidate
    # response cross-checks report counts against the actual source rows.
    for field in (
        "project_id",
        "source_input_sha256",
        "candidate_count",
        "source_image_count",
        "source_organism_count",
        "declared_experimental_unit_count",
        "date_qc_pass_series_count",
        "excluded_series_count",
        "excluded_source_count",
        "qc_status_counts",
    ):
        altered = deepcopy(payload)
        if field == "project_id":
            altered["candidate_report"][field] = "unrelated-project"
        elif field == "source_input_sha256":
            altered["candidate_report"][field] = "0" * 64
        elif field == "qc_status_counts":
            altered["candidate_report"][field] = {"missing_timestamps": 99}
        else:
            altered["candidate_report"][field] += 1
        excluded_fields = {
            "schema_version",
            "report_sha256",
            "evidence_level",
            "review_gate",
        }
        report_values = {
            **{
                key: value
                for key, value in altered["candidate_report"].items()
                if key not in excluded_fields
            },
            "algorithm_version": "ecology-candidate-report-0001",
        }
        altered["candidate_report"]["report_sha256"] = canonical_json_sha256(
            report_values
        )
        # The standalone report contract checks the digest, but the source
        # response also requires exact correspondence with its source rows.
        EcologyCandidateReport.model_validate(altered["candidate_report"])
        with pytest.raises(PydanticValidationError, match="report does not match"):
            EcologyMeasurementCandidatesResponse.model_validate(altered)

    # Older persisted candidate payloads without a report remain readable.
    legacy = deepcopy(payload)
    legacy.pop("candidate_report")
    assert EcologyMeasurementCandidatesResponse.model_validate(legacy).candidate_report is None
