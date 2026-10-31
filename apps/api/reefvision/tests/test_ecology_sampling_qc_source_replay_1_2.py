"""Saved ecological UTC sampling QC must replay from its actual source observations."""

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


def test_api_and_saved_workflow_sampling_qc_replay_from_source(client: TestClient) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row
        for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == response.json()

    for payload in (response.json(), artifacts[0]["payload_json"]):
        parsed = EcologyMeasurementCandidatesResponse.model_validate(payload)
        assert parsed.source_fingerprint_contract == "ecology-measurement-candidates-0021"
        assert parsed.sampling_date_qc
        assert parsed.evidence_level == "linked_unverified"
        assert parsed.review_gate == "scientist_review_required"

    # Re-signing a changed *saved* QC row is not scientific source verification.
    saved = EcologyMeasurementCandidatesResponse.model_validate(artifacts[0]["payload_json"])
    changed_qc = saved.sampling_date_qc[0].model_copy(
        update={"source_image_ids": ["fabricated-image"]}
    )
    forged = _resign_derived_evidence(
        saved.model_copy(update={"sampling_date_qc": [changed_qc, *saved.sampling_date_qc[1:]]})
    )
    with pytest.raises(PydanticValidationError, match="sampling QC does not match source"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("candidate_count", 1),
        ("source_image_ids", ["fabricated-image"]),
        ("sampling_dates_utc", ["2026-04-01", "2026-04-05"]),
        ("duplicate_sampling_dates_utc", ["2026-04-03"]),
        ("missing_timestamp_image_ids", ["fabricated-image"]),
        ("reused_image_sha256", ["a" * 64]),
    ],
)
def test_rehashed_sampling_qc_cannot_invent_dates_or_replicates(
    client: TestClient, field: str, replacement: int | list[str]
) -> None:
    original = _dated_artifact(client)
    assert EcologyMeasurementCandidatesResponse.model_validate(
        original.model_dump(mode="json")
    ).sampling_date_qc[0].qc_status == "date_series_candidate"
    altered = original.sampling_date_qc[0].model_copy(update={field: replacement})
    forged = _resign_derived_evidence(
        original.model_copy(update={"sampling_date_qc": [altered]})
    )
    with pytest.raises(PydanticValidationError, match="sampling QC does not match source"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_rehashed_qc_roster_cannot_hide_or_multiply_observation_series(
    client: TestClient, mode: str
) -> None:
    original = _dated_artifact(client)
    rows = [] if mode == "missing" else original.sampling_date_qc * 2
    forged = _resign_derived_evidence(
        original.model_copy(update={"sampling_date_qc": rows})
    ).model_copy(update={"candidate_report": None})
    with pytest.raises(PydanticValidationError, match="sampling QC does not match source"):
        EcologyMeasurementCandidatesResponse.model_validate(forged.model_dump(mode="json"))


def test_legacy_sampling_qc_artifact_remains_unverified_and_readable(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    legacy = original.model_copy(
        update={
            "source_fingerprint_contract": "ecology-measurement-candidates-0020",
            "sampling_date_qc": [
                original.sampling_date_qc[0].model_copy(
                    update={"sampling_dates_utc": ["historical-unchecked"]}
                )
            ],
        }
    )
    parsed = EcologyMeasurementCandidatesResponse.model_validate(legacy.model_dump(mode="json"))
    assert parsed.sampling_date_qc[0].sampling_dates_utc == ["historical-unchecked"]
    assert parsed.review_gate == "scientist_review_required"
    assert parsed.evidence_level == "linked_unverified"
