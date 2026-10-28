"""Canonical biological-unit date QC without laundering unverified provenance."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from reefvision.schemas.ecology_measurement_candidates import (
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
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import (
    _dated_artifact,
    _resign_derived_evidence,
)
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def _with_followup_label(
    original: EcologyMeasurementCandidatesResponse,
    label: str,
) -> EcologyMeasurementCandidatesResponse:
    """Recompute every derived record before signing a changed source label."""
    baseline, followup = original.candidates
    candidates = [
        baseline,
        followup.model_copy(update={"experimental_unit_type": label}),
    ]
    qc = summarize_sampling_date_qc(candidates)
    changes = summarize_projected_endpoint_changes(candidates, qc)
    units = summarize_projected_unit_summaries(candidates, changes)
    return _resign_derived_evidence(
        original.model_copy(
            update={
                "source_fingerprint_contract": "ecology-measurement-candidates-0020",
                "candidates": candidates,
                "sampling_date_qc": qc,
                "projected_visit_coverage": summarize_projected_visit_coverage(candidates),
                "projected_endpoint_changes": changes,
                "projected_unit_summaries": units,
                "projected_population_summaries": summarize_projected_population_summaries(
                    units
                ),
            }
        )
    )


@pytest.mark.parametrize("alias", ["aquarium", "Aquarium", "TankLevel", "aquaria"])
def test_source_linked_aliases_preserve_one_longitudinal_unit_and_csv(
    client: TestClient,
    alias: str,
) -> None:
    original = _dated_artifact(client)
    result = _with_followup_label(original, alias)
    assert len(result.sampling_date_qc) == 1
    assert result.sampling_date_qc[0].qc_status == "date_series_candidate"
    assert len(result.projected_endpoint_changes) == 1
    assert len(result.projected_unit_summaries) == 1
    assert result.projected_unit_summaries[0].experimental_unit_type == "tank"
    assert result.projected_unit_summaries[0].unit_status == "candidate"
    assert len(result.projected_population_summaries) == 1
    assert result.projected_population_summaries[0].declared_unit_count == 1
    assert len(result.projected_visit_coverage) == 2
    assert all(row.experimental_unit_type == "tank" for row in result.projected_visit_coverage)
    assert result.candidates[-1].experimental_unit_type == alias
    assert result.review_gate == "scientist_review_required"
    assert result.evidence_level == "linked_unverified"

    rows = list(csv.DictReader(StringIO(render_ecology_series_qc_csv(result))))
    assert len(rows) == 1
    assert rows[0]["qc_status"] == "date_series_candidate"
    assert rows[0]["source_fingerprint_rechecked"] == "true"
    assert rows[0]["review_gate"] == "scientist_review_required"


def test_alias_correction_changes_fingerprint_without_inflating_replicates(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    same_label = _with_followup_label(original, "tank")
    alias = _with_followup_label(original, "aquarium")
    assert same_label.input_sha256 != alias.input_sha256
    assert same_label.projected_population_summaries == alias.projected_population_summaries
    assert alias.projected_population_summaries[0].declared_unit_count == 1


def test_conflicting_biological_levels_still_exclude_endpoint(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    baseline, followup = original.candidates
    changed = followup.model_copy(update={"experimental_unit_type": "colony"})
    qc = summarize_sampling_date_qc([baseline, changed])
    assert len(qc) == 1
    assert qc[0].qc_status == "identity_context_changed"
    assert summarize_projected_endpoint_changes([baseline, changed], qc) == []


def test_saved_workflow_source_replay_uses_same_canonical_date_qc(
    client: TestClient,
) -> None:
    project_id, source = _source(client)
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        row for row in run["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    saved = EcologyMeasurementCandidatesResponse.model_validate(artifacts[0]["payload_json"])
    assert saved.candidates
    assert saved.candidates[0].image_id == source.image_id

    first = saved.candidates[0].model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-1",
        }
    )
    followup = first.model_copy(
        update={
            "image_id": "review-pending-followup",
            "image_sha256": "a" * 64,
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "experimental_unit_type": "aquarium",
        }
    )
    qc = summarize_sampling_date_qc([first, followup])
    assert qc[0].qc_status == "date_series_candidate"
    changes = summarize_projected_endpoint_changes([first, followup], qc)
    assert len(changes) == 1
    assert changes[0].evidence_level == "linked_unverified"
    assert changes[0].review_gate == "scientist_review_required"
