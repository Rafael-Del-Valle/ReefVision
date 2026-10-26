"""Projected endpoint CSV, signed source arithmetic, and saved-workflow parity."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyCandidateReport,
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_report_export import render_ecology_series_qc_csv
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_endpoint_changes,
    summarize_projected_population_summaries,
    summarize_projected_unit_summaries,
    summarize_projected_visit_coverage,
    summarize_sampling_date_qc,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def _dated_artifact(client: TestClient) -> EcologyMeasurementCandidatesResponse:
    project_id, source = _source(client)
    result = client.get(f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates")
    assert result.status_code == 200
    original = EcologyMeasurementCandidatesResponse.model_validate(result.json())
    baseline = source.model_copy(
        update={
            "organism_key": "coral-A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    final = baseline.model_copy(
        update={
            "image_id": "followup-image",
            "image_sha256": "a" * 64,
            "annotation_evidence_id": "followup-annotation",
            "calibration_evidence_id": "followup-calibration",
            "capture_timestamp_utc": datetime(2026, 4, 5, 8, tzinfo=UTC),
            "value": baseline.value + 2,
        }
    )
    candidates = [baseline, final]
    qc = summarize_sampling_date_qc(candidates)
    visits = summarize_projected_visit_coverage(candidates)
    changes = summarize_projected_endpoint_changes(candidates, qc)
    units = summarize_projected_unit_summaries(candidates, changes)
    population = summarize_projected_population_summaries(units)
    source_values = {
        "algorithm_version": original.source_fingerprint_contract,
        "project_id": project_id,
        "registry_history_sha256": original.source_registry_history_sha256,
        "registry_image_evidence_sha256": original.source_image_evidence_sha256,
        "registry_annotation_evidence_sha256": original.source_annotation_evidence_sha256,
        "registry_calibration_evidence_sha256": original.source_calibration_evidence_sha256,
        "candidates": [row.model_dump(mode="json") for row in candidates],
        "sampling_date_qc": [row.model_dump(mode="json") for row in qc],
        "projected_visit_coverage": [row.model_dump(mode="json") for row in visits],
        "projected_endpoint_changes": [row.model_dump(mode="json") for row in changes],
        "projected_unit_summaries": [row.model_dump(mode="json") for row in units],
        "projected_population_summaries": [row.model_dump(mode="json") for row in population],
        "exclusions": [],
    }
    fingerprint = canonical_json_sha256(source_values)
    report_values = {
        "algorithm_version": "ecology-candidate-report-0001",
        "project_id": project_id,
        "source_input_sha256": fingerprint,
        "candidate_count": 2,
        "source_image_count": 2,
        "source_organism_count": 1,
        "declared_experimental_unit_count": 1,
        "date_qc_pass_series_count": 1,
        "excluded_series_count": 0,
        "excluded_source_count": 0,
        "qc_status_counts": {"date_series_candidate": 1},
    }
    report = EcologyCandidateReport.model_validate(
        {**report_values, "report_sha256": canonical_json_sha256(report_values)}
    )
    return original.model_copy(
        update={
            "candidates": candidates,
            "candidate_count": 2,
            "sampling_date_qc": qc,
            "projected_visit_coverage": visits,
            "projected_endpoint_changes": changes,
            "projected_unit_summaries": units,
            "projected_population_summaries": population,
            "exclusions": [],
            "input_sha256": fingerprint,
            "candidate_report": report,
        }
    )


def test_series_export_matches_api_and_saved_workflow(client: TestClient) -> None:
    project_id, _ = _source(client)
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    api = client.get(path)
    csv_response = client.get(path + "/report-series.csv")
    assert api.status_code == csv_response.status_code == 200
    rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert rows
    assert all(row["projected_endpoint_status"] == "excluded_by_date_qc" for row in rows)
    assert all(row["absolute_change"] == "" for row in rows)
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    saved = EcologyMeasurementCandidatesResponse.model_validate(artifacts[0]["payload_json"])
    assert render_ecology_series_qc_csv(saved) == csv_response.text


def test_projected_endpoint_csv_reports_dated_arithmetic_and_sources(
    client: TestClient,
) -> None:
    artifact = _dated_artifact(client)
    rows = list(csv.DictReader(StringIO(render_ecology_series_qc_csv(artifact))))
    assert len(rows) == 1
    row = rows[0]
    change = artifact.projected_endpoint_changes[0]
    assert row["projected_endpoint_status"] == "projected_unverified"
    assert row["source_fingerprint_rechecked"] == "true"
    assert row["baseline_image_id"] == change.baseline_image_id
    assert row["final_image_id"] == change.final_image_id
    assert float(row["absolute_change"]) == pytest.approx(2)
    assert float(row["elapsed_days"]) == pytest.approx(2)
    assert float(row["projected_absolute_change_per_day"]) == pytest.approx(1)
    detail = json.loads(row["projected_endpoint_json"])
    assert detail["baseline_calibration_evidence_id"] == change.baseline_calibration_evidence_id
    assert detail["final_calibration_evidence_id"] == change.final_calibration_evidence_id
    assert detail["review_gate"] == "scientist_review_required"
    assert detail["evidence_level"] == "linked_unverified"


def test_projected_csv_rejects_tampered_or_missing_endpoints(client: TestClient) -> None:
    artifact = _dated_artifact(client)
    forged = artifact.projected_endpoint_changes[0].model_copy(update={"absolute_change": 999.0})
    for changes in ([forged], []):
        tampered = artifact.model_copy(update={"projected_endpoint_changes": changes})
        with pytest.raises(ValidationError, match="Projected endpoint evidence"):
            render_ecology_series_qc_csv(tampered)


def _resign_derived_evidence(
    artifact: EcologyMeasurementCandidatesResponse,
) -> EcologyMeasurementCandidatesResponse:
    """Re-sign forged data to prove the exporter checks science, not only hashes."""
    source_values = {
        "algorithm_version": artifact.source_fingerprint_contract,
        "project_id": artifact.project_id,
        "registry_history_sha256": artifact.source_registry_history_sha256,
        "registry_image_evidence_sha256": artifact.source_image_evidence_sha256,
        "registry_annotation_evidence_sha256": artifact.source_annotation_evidence_sha256,
        "registry_calibration_evidence_sha256": artifact.source_calibration_evidence_sha256,
        "candidates": [row.model_dump(mode="json") for row in artifact.candidates],
        "sampling_date_qc": [row.model_dump(mode="json") for row in artifact.sampling_date_qc],
        "projected_visit_coverage": [
            row.model_dump(mode="json") for row in artifact.projected_visit_coverage
        ],
        "projected_endpoint_changes": [
            row.model_dump(mode="json") for row in artifact.projected_endpoint_changes
        ],
        "projected_unit_summaries": [
            row.model_dump(mode="json") for row in artifact.projected_unit_summaries
        ],
        "projected_population_summaries": [
            row.model_dump(mode="json") for row in artifact.projected_population_summaries
        ],
        "exclusions": [row.model_dump(mode="json") for row in artifact.exclusions],
    }
    new_sha = canonical_json_sha256(source_values)
    report = artifact.candidate_report
    assert report is not None
    report_values = report.model_dump(
        mode="json",
        exclude={"schema_version", "report_sha256", "evidence_level", "review_gate"},
    )
    report_values["source_input_sha256"] = new_sha
    signed_report = report.model_copy(
        update={
            "source_input_sha256": new_sha,
            "report_sha256": canonical_json_sha256(report_values),
        }
    )
    return artifact.model_copy(update={"input_sha256": new_sha, "candidate_report": signed_report})


@pytest.mark.parametrize(
    ("field", "patch", "error"),
    [
        ("projected_visit_coverage", {"linked_measurement_count": 999}, "visit coverage"),
        ("projected_unit_summaries", {"mean_absolute_change": 999.0}, "unit summaries"),
        (
            "projected_population_summaries",
            {"mean_unit_absolute_change": 999.0},
            "population summaries",
        ),
    ],
)
def test_projected_csv_rejects_resigned_forged_aggregates(
    client: TestClient,
    field: str,
    patch: dict[str, float | int],
    error: str,
) -> None:
    original = _dated_artifact(client)
    records = getattr(original, field)
    assert records
    altered = [records[0].model_copy(update=patch), *records[1:]]
    tampered = _resign_derived_evidence(original.model_copy(update={field: altered}))
    with pytest.raises(ValidationError, match=f"Projected {error} evidence"):
        render_ecology_series_qc_csv(tampered)


@pytest.mark.parametrize(
    "patch",
    [
        {"absolute_change": 999.0},
        {"baseline_image_id": "forged-baseline"},
        {"final_calibration_evidence_id": "forged-calibration"},
    ],
)
def test_projected_csv_rejects_resigned_forged_endpoint_evidence(
    client: TestClient,
    patch: dict[str, float | str],
) -> None:
    """A valid new fingerprint cannot certify fabricated longitudinal evidence."""
    original = _dated_artifact(client)
    endpoint = original.projected_endpoint_changes[0].model_copy(update=patch)
    forged = _resign_derived_evidence(
        original.model_copy(update={"projected_endpoint_changes": [endpoint]})
    )
    with pytest.raises(ValidationError, match="Projected endpoint evidence"):
        render_ecology_series_qc_csv(forged)


def test_legacy_endpoint_absence_remains_explicit(client: TestClient) -> None:
    artifact = _dated_artifact(client)
    legacy = artifact.model_copy(
        update={
            "source_fingerprint_contract": None,
            "source_image_evidence_sha256": None,
            "source_annotation_evidence_sha256": None,
            "projected_endpoint_changes": [],
        }
    )
    rows = list(csv.DictReader(StringIO(render_ecology_series_qc_csv(legacy))))
    assert rows[0]["projected_endpoint_status"] == "legacy_unavailable"
    assert rows[0]["source_fingerprint_rechecked"] == "false"
    assert rows[0]["absolute_change"] == ""
    assert rows[0]["projected_endpoint_json"] == ""
