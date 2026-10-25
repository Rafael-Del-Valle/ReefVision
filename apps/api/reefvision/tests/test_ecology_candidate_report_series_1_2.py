"""Detailed ecological QC CSV: traceability, safety, and saved-workflow parity."""

from __future__ import annotations

import csv
import json
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_report_export import render_ecology_series_qc_csv
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def test_series_qc_csv_matches_typed_api_and_saved_workflow(client: TestClient) -> None:
    project_id, source = _source(client)
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    standalone = client.get(path)
    assert standalone.status_code == 200, standalone.text
    payload = standalone.json()
    csv_response = client.get(path + "/report-series.csv")
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert len(rows) == len(payload["sampling_date_qc"]) == 2
    assert [row["metric"] for row in rows] == ["box_height", "box_width"]
    for row in rows:
        source_row = next(
            item for item in payload["sampling_date_qc"] if item["metric"] == row["metric"]
        )
        assert row["project_id"] == project_id
        assert row["source_input_sha256"] == payload["input_sha256"]
        assert row["report_sha256"] == payload["candidate_report"]["report_sha256"]
        assert row["qc_status"] == source_row["qc_status"] == "missing_timestamps"
        assert int(row["candidate_count"]) == source_row["candidate_count"]
        assert json.loads(row["source_image_ids_json"]) == source_row["source_image_ids"]
        assert source.image_id in json.loads(row["source_image_ids_json"])
        assert json.loads(row["missing_timestamp_image_ids_json"]) == (
            source_row["missing_timestamp_image_ids"]
        )
        assert json.loads(row["sampling_dates_utc_json"]) == []
        assert row["evidence_level"] == "linked_unverified"
        assert row["review_gate"] == "scientist_review_required"

    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        item
        for item in workflow["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    persisted = EcologyMeasurementCandidatesResponse.model_validate(
        artifacts[0]["payload_json"]
    )
    assert render_ecology_series_qc_csv(persisted) == csv_response.text
    assert render_ecology_series_qc_csv(persisted) == render_ecology_series_qc_csv(
        persisted.model_copy(update={"sampling_date_qc": list(reversed(persisted.sampling_date_qc))})
    )


def test_series_qc_csv_fails_closed_on_stale_report_or_duplicate_qc(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    assert payload.candidate_report is not None
    stale = payload.model_copy(
        update={
            "candidate_report": payload.candidate_report.model_copy(
                update={"qc_status_counts": {"date_series_candidate": 2}}
            )
        }
    )
    with pytest.raises(ValidationError, match="QC totals"):
        render_ecology_series_qc_csv(stale)
    duplicated = payload.model_copy(
        update={"sampling_date_qc": [*payload.sampling_date_qc, payload.sampling_date_qc[0]]}
    )
    with pytest.raises(ValidationError, match="Duplicate"):
        render_ecology_series_qc_csv(duplicated)


def test_series_qc_csv_escapes_spreadsheet_formulas_and_preserves_delimiters(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    first = payload.sampling_date_qc[0].model_copy(
        update={"organism_key": "=SUM(1,2)", "source_image_ids": ["image;1", "image,2"]}
    )
    altered = payload.model_copy(
        update={"sampling_date_qc": [first, *payload.sampling_date_qc[1:]]}
    )
    rows = list(csv.DictReader(StringIO(render_ecology_series_qc_csv(altered))))
    assert rows[0]["organism_key"] == "'=SUM(1,2)"
    assert json.loads(rows[0]["source_image_ids_json"]) == ["image;1", "image,2"]
