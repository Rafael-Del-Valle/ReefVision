"""Persisted projected endpoints must replay their UTC arithmetic, not claim growth."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
    EcologyProjectedEndpointChange,
)
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_endpoint_changes,
    summarize_sampling_date_qc,
)
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def test_projected_endpoint_replay_rejects_changed_scientific_arithmetic(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201

    standalone = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert standalone.status_code == 200, standalone.text
    saved = _workflow(client, project_id)
    assert saved["run"]["status"] == "succeeded"
    artifacts = [
        row for row in saved["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == standalone.json()

    source = EcologyMeasurementCandidate.model_validate(standalone.json()["candidates"][0])
    first = source.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    last = first.model_copy(
        update={
            "image_id": "independent-followup-image",
            "image_sha256": "b" * 64,
            "annotation_evidence_id": "followup-annotation",
            "calibration_evidence_id": "followup-calibration",
            "capture_timestamp_utc": datetime(2026, 4, 5, 8, tzinfo=UTC),
            "value": first.value + 2.5,
        }
    )
    changes = summarize_projected_endpoint_changes(
        [first, last], summarize_sampling_date_qc([first, last])
    )
    assert len(changes) == 1
    original = changes[0].model_dump(mode="json")
    assert EcologyProjectedEndpointChange.model_validate(original).model_dump(
        mode="json"
    ) == original

    # A previously saved typed result can omit optional later-added slopes.
    legacy = dict(original)
    legacy.pop("projected_absolute_change_per_day")
    legacy.pop("projected_baseline_percent_change_per_day")
    assert EcologyProjectedEndpointChange.model_validate(
        legacy
    ).projected_absolute_change_per_day is None

    # Equivalent offset timestamps must replay the same UTC instants.
    offset = dict(original)
    offset["baseline_capture_timestamp_utc"] = "2026-04-03T04:00:00-04:00"
    offset["final_capture_timestamp_utc"] = "2026-04-05T04:00:00-04:00"
    assert EcologyProjectedEndpointChange.model_validate(offset).elapsed_days == 2

    # Typed saved-workflow payloads reject changed endpoint calculations
    # even if the attacker keeps all lineage digest strings intact.
    typed_artifact = dict(standalone.json())
    typed_artifact["projected_endpoint_changes"] = [original]
    assert len(
        EcologyMeasurementCandidatesResponse.model_validate(
            typed_artifact
        ).projected_endpoint_changes
    ) == 1

    mutations: list[tuple[str, object]] = [
        ("absolute_change", 99.0),
        ("percent_change", 99.0),
        ("elapsed_days", 3.0),
        ("projected_absolute_change_per_day", 99.0),
        ("projected_baseline_percent_change_per_day", 99.0),
        ("baseline_capture_timestamp_utc", "2026-04-03T08:00:00"),
        ("final_capture_timestamp_utc", "2026-04-03T16:00:00Z"),
        ("final_image_id", first.image_id),
    ]
    for field, replacement in mutations:
        tampered = dict(original)
        tampered[field] = replacement
        with pytest.raises(PydanticValidationError, match="Projected endpoint"):
            EcologyProjectedEndpointChange.model_validate(tampered)
        forged_artifact = dict(typed_artifact)
        forged_artifact["projected_endpoint_changes"] = [tampered]
        with pytest.raises(PydanticValidationError, match="Projected endpoint"):
            EcologyMeasurementCandidatesResponse.model_validate(forged_artifact)

    assert original["evidence_level"] == "linked_unverified"
    assert original["review_gate"] == "scientist_review_required"
