"""Replayed ecological summaries cannot forge visits or independent units."""

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


def test_standalone_and_executed_saved_workflow_replay_current_source(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    api = client.get(f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates")
    assert api.status_code == 200, api.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == api.json()
    for payload in (api.json(), artifacts[0]["payload_json"]):
        replay = EcologyMeasurementCandidatesResponse.model_validate(payload)
        assert replay.source_fingerprint_contract == "ecology-measurement-candidates-0021"
        assert replay.review_gate == "scientist_review_required"
        assert replay.evidence_level == "linked_unverified"


@pytest.mark.parametrize(
    ("field", "patch", "error"),
    [
        (
            "projected_visit_coverage",
            {"linked_measurement_count": 99},
            "visit coverage",
        ),
        (
            "projected_visit_coverage",
            {"no_linked_measurement_organism_keys": ["fabricated-coral"]},
            "visit coverage",
        ),
        (
            "projected_unit_summaries",
            {"mean_absolute_change": 999.0},
            "unit summaries",
        ),
        (
            "projected_unit_summaries",
            {"experimental_unit_id": "fabricated-tank"},
            "unit summaries",
        ),
        (
            "projected_unit_summaries",
            {"complete_organism_keys": []},
            "unit summaries",
        ),
        (
            "projected_population_summaries",
            {"declared_unit_count": 2},
            "population summaries",
        ),
        (
            "projected_population_summaries",
            {"experimental_unit_ids": ["tank-A", "fabricated-tank"]},
            "population summaries",
        ),
        (
            "projected_population_summaries",
            {"mean_unit_absolute_change": 999.0},
            "population summaries",
        ),
        (
            "projected_population_summaries",
            {"design_review_blockers": []},
            "population summaries",
        ),
    ],
)
def test_rehashed_derived_summary_cannot_override_source_evidence(
    client: TestClient,
    field: str,
    patch: dict[str, object],
    error: str,
) -> None:
    original = _dated_artifact(client)
    rows = getattr(original, field)
    assert rows
    altered = [rows[0].model_copy(update=patch), *rows[1:]]
    forged = _resign_derived_evidence(original.model_copy(update={field: altered}))
    with pytest.raises(PydanticValidationError, match=error):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("projected_visit_coverage", "visit coverage"),
        ("projected_unit_summaries", "unit summaries"),
        ("projected_population_summaries", "population summaries"),
    ],
)
@pytest.mark.parametrize("operation", ["omit", "duplicate"])
def test_rehashed_missing_or_duplicate_summary_rows_cannot_change_denominators(
    client: TestClient, field: str, error: str, operation: str
) -> None:
    original = _dated_artifact(client)
    rows = getattr(original, field)
    assert rows
    altered = [] if operation == "omit" else [*rows, rows[0]]
    forged = _resign_derived_evidence(original.model_copy(update={field: altered}))
    with pytest.raises(PydanticValidationError, match=error):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_saved_workflow_rejects_rehashed_fabricated_visit(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    payload = next(
        row["payload_json"]
        for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    )
    saved = EcologyMeasurementCandidatesResponse.model_validate(payload)
    assert saved.projected_visit_coverage == []
    # This undated real source has no measured UTC visit. A fabricated visit
    # from a separate source must fail even after both digests are recomputed.
    fabricated_visit = _dated_artifact(client).projected_visit_coverage[0]
    forged = _resign_derived_evidence(
        saved.model_copy(update={"projected_visit_coverage": [fabricated_visit]})
    )
    with pytest.raises(PydanticValidationError, match="visit coverage"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_historical_summary_contract_is_readable_but_never_verified(
    client: TestClient,
) -> None:
    current = _dated_artifact(client)
    altered = current.projected_unit_summaries[0].model_copy(update={"mean_absolute_change": 999.0})
    historical = current.model_copy(
        update={
            "source_fingerprint_contract": "ecology-measurement-candidates-0020",
            "projected_unit_summaries": [altered],
        }
    )
    parsed = EcologyMeasurementCandidatesResponse.model_validate(historical.model_dump(mode="json"))
    assert parsed.source_fingerprint_contract == "ecology-measurement-candidates-0020"
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"
