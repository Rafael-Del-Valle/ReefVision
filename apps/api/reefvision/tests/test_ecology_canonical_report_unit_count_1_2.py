"""Signed ecological reports must count physical units, not aliases as replicates."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
import pytest

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_measurement_candidates import (
    count_declared_ecological_units,
    summarize_projected_endpoint_changes,
    summarize_projected_population_summaries,
    summarize_projected_unit_summaries,
    summarize_projected_visit_coverage,
    summarize_sampling_date_qc,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import _resign_derived_evidence
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def _signed_alias_artifact(client: TestClient) -> EcologyMeasurementCandidatesResponse:
    """Start from an executed saved workflow; synthesize unverified alias evidence."""
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
    original = EcologyMeasurementCandidatesResponse.model_validate(saved)
    assert original.candidate_report is not None
    source = original.candidates[0].model_copy(
        update={
            "organism_key": "coral-A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "physical-tank-1",
        }
    )
    alias = source.model_copy(
        update={
            "organism_key": "coral-B",
            "experimental_unit_type": "aquarium",
            "image_id": "coral-B-image",
            "image_sha256": "b" * 64,
            "annotation_evidence_id": "coral-B-annotation-link",
            "annotation_id": "coral-B-annotation",
            "annotation_sha256": "c" * 64,
            "calibration_evidence_id": "coral-B-calibration-link",
            "calibration_sha256": "d" * 64,
        }
    )
    candidates = [source, alias]
    assert count_declared_ecological_units(candidates, canonicalize=False) == 2
    assert count_declared_ecological_units(candidates, canonicalize=True) == 1
    qc = summarize_sampling_date_qc(candidates)
    visits = summarize_projected_visit_coverage(candidates)
    changes = summarize_projected_endpoint_changes(candidates, qc)
    units = summarize_projected_unit_summaries(candidates, changes)
    population = summarize_projected_population_summaries(units)
    assert len(units) == 1
    assert not population  # Undated source rows are never promoted to growth.

    counts: dict[str, int] = {}
    for row in qc:
        counts[row.qc_status] = counts.get(row.qc_status, 0) + 1
    passed = counts.get("date_series_candidate", 0)
    report = original.candidate_report.model_copy(
        update={
            "candidate_count": len(candidates),
            "source_image_count": len({row.image_id for row in candidates}),
            "source_organism_count": len({row.organism_key for row in candidates}),
            "declared_experimental_unit_count": 1,
            "date_qc_pass_series_count": passed,
            "excluded_series_count": len(qc) - passed,
            "qc_status_counts": counts,
        }
    )
    return _resign_derived_evidence(
        original.model_copy(
            update={
                "candidates": candidates,
                "candidate_count": len(candidates),
                "sampling_date_qc": qc,
                "projected_visit_coverage": visits,
                "projected_endpoint_changes": changes,
                "projected_unit_summaries": units,
                "projected_population_summaries": population,
                "candidate_report": report,
            }
        )
    )


def test_current_saved_workflow_alias_report_rejects_resigned_inflated_unit_count(
    client: TestClient,
) -> None:
    current = _signed_alias_artifact(client)
    payload = current.model_dump(mode="json")
    parsed = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert parsed.candidate_report is not None
    assert parsed.candidate_report.declared_experimental_unit_count == 1
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"

    report = current.candidate_report.model_copy(update={"declared_experimental_unit_count": 2})
    forged = _resign_derived_evidence(current.model_copy(update={"candidate_report": report}))
    with pytest.raises(PydanticValidationError, match="report does not match source rows"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_historical_literal_alias_report_remains_readable_but_unverified(
    client: TestClient,
) -> None:
    current = _signed_alias_artifact(client)
    assert current.candidate_report is not None
    report = current.candidate_report.model_copy(update={"declared_experimental_unit_count": 2})
    signed = _resign_derived_evidence(current.model_copy(update={"candidate_report": report}))
    historical = signed.model_copy(
        update={"source_fingerprint_contract": "ecology-measurement-candidates-0020"}
    )
    parsed = EcologyMeasurementCandidatesResponse.model_validate(historical.model_dump(mode="json"))
    assert parsed.candidate_report is not None
    assert parsed.candidate_report.declared_experimental_unit_count == 2
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"
