"""Strict source-linked ecological evidence for API and saved-workflow replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def _candidate_payload() -> dict[str, object]:
    return {
        "organism_key": "coral-16",
        "identity_revision": 1,
        "parent_colony_key": None,
        "experimental_unit_type": "tank",
        "experimental_unit_id": "tank-1",
        "image_id": "image-1",
        "image_sha256": "a" * 64,
        "annotation_evidence_id": "annotation-evidence-1",
        "calibration_evidence_id": "calibration-evidence-1",
        "annotation_kind": "box",
        "annotation_id": "annotation-1",
        "annotation_revision": 1,
        "annotation_sha256": "b" * 64,
        "calibration_sha256": "c" * 64,
        "metric": "box_width",
        "value": 3.2,
        "unit": "mm",
        "capture_timestamp_utc": "2026-04-03T08:00:00Z",
        "capture_time_status": "timezone_aware",
    }


@pytest.mark.parametrize("bad_value", [True, False, "3.2", None, [], {}])
def test_linked_measurements_reject_coerced_numeric_values(bad_value: object) -> None:
    payload = _candidate_payload()
    payload["value"] = bad_value
    with pytest.raises(SchemaValidationError, match="JSON number"):
        EcologyMeasurementCandidate.model_validate(payload)


@pytest.mark.parametrize(
    "bad_timestamp",
    [0, 1775203200, "1775203200", "2026-04-03", True],
)
def test_linked_measurements_reject_inferred_capture_times(bad_timestamp: object) -> None:
    payload = _candidate_payload()
    payload["capture_timestamp_utc"] = bad_timestamp
    with pytest.raises(SchemaValidationError, match="explicit ISO 8601"):
        EcologyMeasurementCandidate.model_validate(payload)


def test_linked_measurements_keep_explicit_offsets_and_undated_evidence() -> None:
    payload = _candidate_payload()
    baseline = EcologyMeasurementCandidate.model_validate(payload)
    assert baseline.value == 3.2
    assert baseline.capture_timestamp_utc == datetime(2026, 4, 3, 8, tzinfo=UTC)
    assert baseline.evidence_level == "linked_unverified"
    assert baseline.review_gate == "scientist_review_required"

    payload["value"] = 3
    payload["capture_timestamp_utc"] = "2026-04-03T10:00:00+02:00"
    offset = EcologyMeasurementCandidate.model_validate(payload)
    assert offset.value == 3.0
    assert offset.capture_timestamp_utc is not None
    assert offset.capture_timestamp_utc.astimezone(UTC) == baseline.capture_timestamp_utc

    payload["capture_timestamp_utc"] = None
    payload["capture_time_status"] = "timezone_missing"
    undated = EcologyMeasurementCandidate.model_validate(payload)
    assert undated.capture_timestamp_utc is None
    assert undated.review_gate == "scientist_review_required"


def test_saved_workflow_source_replay_rejects_coerced_measurements_and_epochs(
    client: TestClient,
) -> None:
    """A saved executable source remains valid; tampered reimports fail closed."""
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        row for row in run["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    saved = artifacts[0]["payload_json"]
    assert saved == response.json()
    assert EcologyMeasurementCandidatesResponse.model_validate(saved).candidate_count > 0

    for field, bad_value, error in (
        ("value", "3.2", "JSON number"),
        ("value", True, "JSON number"),
        ("capture_timestamp_utc", 1775203200, "explicit ISO 8601"),
    ):
        tampered = deepcopy(saved)
        tampered["candidates"][0][field] = bad_value
        if field == "capture_timestamp_utc":
            tampered["candidates"][0]["capture_time_status"] = "timezone_aware"
        with pytest.raises(SchemaValidationError, match=error):
            EcologyMeasurementCandidatesResponse.model_validate(tampered)
