"""Reproducible ecological QC report: API, CSV and saved Workflow Builder parity."""

from __future__ import annotations

import csv
from io import StringIO

from fastapi.testclient import TestClient

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
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
