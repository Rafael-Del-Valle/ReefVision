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
from reefvision.services.ecology_candidate_report_export import (
    _csv_identifier,
    _json_array,
    render_ecology_series_qc_csv,
)
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
        assert row["source_fingerprint_rechecked"] == "true"
        assert row["qc_status"] == source_row["qc_status"] == "missing_timestamps"
        assert int(row["candidate_count"]) == source_row["candidate_count"]
        assert json.loads(row["source_image_ids_json"]) == source_row["source_image_ids"]
        assert source.image_id in json.loads(row["source_image_ids_json"])
        assert (
            json.loads(row["missing_timestamp_image_ids_json"])
            == (source_row["missing_timestamp_image_ids"])
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
    persisted = EcologyMeasurementCandidatesResponse.model_validate(artifacts[0]["payload_json"])
    assert render_ecology_series_qc_csv(persisted) == csv_response.text
    assert render_ecology_series_qc_csv(persisted) == render_ecology_series_qc_csv(
        persisted.model_copy(
            update={"sampling_date_qc": list(reversed(persisted.sampling_date_qc))}
        )
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
    rows = list(csv.DictReader(StringIO(render_ecology_series_qc_csv(payload))))
    assert rows and rows[0]["source_fingerprint_rechecked"] == "true"
    # Formula safety is tested on the serializer directly: modifying source
    # records without updating their immutable input digest must now fail.
    assert _csv_identifier("=SUM(1,2)") == "'=SUM(1,2)"
    assert _csv_identifier("+2+3") == "'+2+3"
    assert _csv_identifier("-2+3") == "'-2+3"
    assert _csv_identifier("@SUM(1,2)") == "'@SUM(1,2)"
    assert _csv_identifier("  @SUM(1,2)") == "'  @SUM(1,2)"
    assert json.loads(_json_array(["image;1", "image,2"])) == ["image;1", "image,2"]


def test_series_qc_csv_rejects_forged_per_series_sources_and_candidate_counts(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    forged_qc = payload.sampling_date_qc[0].model_copy(
        update={"source_image_ids": ["forged-image"]}
    )
    altered = payload.model_copy(
        update={"sampling_date_qc": [forged_qc, *payload.sampling_date_qc[1:]]}
    )
    with pytest.raises(ValidationError, match="QC evidence"):
        render_ecology_series_qc_csv(altered)

    altered_candidate = payload.candidates[0].model_copy(update={"image_id": "forged-image"})
    altered = payload.model_copy(
        update={"candidates": [altered_candidate, *payload.candidates[1:]]}
    )
    with pytest.raises(ValidationError, match="QC evidence"):
        render_ecology_series_qc_csv(altered)

    altered = payload.model_copy(update={"candidate_count": payload.candidate_count + 1})
    with pytest.raises(ValidationError, match="candidate count"):
        render_ecology_series_qc_csv(altered)


def test_series_qc_csv_rejects_stale_denominators_and_report_digest(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    assert payload.candidate_report is not None
    wrong_denominator = payload.model_copy(
        update={
            "candidate_report": payload.candidate_report.model_copy(
                update={"source_image_count": payload.candidate_report.source_image_count + 1}
            )
        }
    )
    with pytest.raises(ValidationError, match="denominators"):
        render_ecology_series_qc_csv(wrong_denominator)

    wrong_digest = payload.model_copy(
        update={
            "candidate_report": payload.candidate_report.model_copy(
                update={"report_sha256": "0" * 64}
            )
        }
    )
    with pytest.raises(ValidationError, match="fingerprint"):
        render_ecology_series_qc_csv(wrong_digest)


def test_series_qc_csv_rechecks_complete_source_fingerprint_and_marks_legacy(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    assert payload.source_fingerprint_contract == "ecology-measurement-candidates-0019"
    assert payload.candidates
    assert '"true"' not in render_ecology_series_qc_csv(payload)  # CSV booleans are plain text

    # A value change leaves date QC and aggregate counts unchanged, but it
    # must never retain the old source-evidence fingerprint.
    candidate = payload.candidates[0]
    altered = payload.model_copy(
        update={
            "candidates": [
                candidate.model_copy(update={"value": candidate.value + 0.25}),
                *payload.candidates[1:],
            ]
        }
    )
    with pytest.raises(ValidationError, match="source input fingerprint"):
        render_ecology_series_qc_csv(altered)

    altered = payload.model_copy(update={"source_annotation_evidence_sha256": "0" * 64})
    with pytest.raises(ValidationError, match="source input fingerprint"):
        render_ecology_series_qc_csv(altered)

    # Pre-contract persisted artifacts remain exportable, but their source
    # digest is explicitly NOT represented as independently rechecked.
    legacy = payload.model_copy(
        update={
            "source_fingerprint_contract": None,
            "source_image_evidence_sha256": None,
            "source_annotation_evidence_sha256": None,
        }
    )
    rows = list(csv.DictReader(StringIO(render_ecology_series_qc_csv(legacy))))
    assert rows and all(row["source_fingerprint_rechecked"] == "false" for row in rows)

    downgraded = payload.model_copy(update={"source_fingerprint_contract": None})
    with pytest.raises(ValidationError, match="contract is missing"):
        render_ecology_series_qc_csv(downgraded)
