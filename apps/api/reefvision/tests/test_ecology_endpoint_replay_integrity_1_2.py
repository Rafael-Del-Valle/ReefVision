"""Persisted projected endpoints must replay their UTC arithmetic, not claim growth."""

from __future__ import annotations

from copy import deepcopy
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
from reefvision.storage.datasets import canonical_json_sha256
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
        row for row in saved["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == standalone.json()

    # The standalone API and executed, persisted Workflow Builder artifact
    # must both replay their v0021 digest, not merely retain a plausible hex
    # string after source candidates or derived ecological summaries change.
    original_payload = standalone.json()
    assert original_payload["source_fingerprint_contract"] == (
        "ecology-measurement-candidates-0021"
    )
    for payload in (original_payload, artifacts[0]["payload_json"]):
        assert (
            EcologyMeasurementCandidatesResponse.model_validate(payload).input_sha256
            == original_payload["input_sha256"]
        )
    for changed_field in ("candidate_value", "candidate_count", "digest", "qc"):
        altered = deepcopy(original_payload)
        if changed_field == "candidate_value":
            altered["candidates"][0]["value"] += 1.0
        elif changed_field == "candidate_count":
            altered["candidate_count"] += 1
        elif changed_field == "digest":
            altered["input_sha256"] = "0" * 64
        else:
            altered["sampling_date_qc"][0]["candidate_count"] += 1
        with pytest.raises(PydanticValidationError, match=r"candidate count|fingerprint"):
            EcologyMeasurementCandidatesResponse.model_validate(altered)

    # Historical v0020 payloads are not retrospectively asserted to follow
    # v0021's canonical digest contract; they remain explicitly legacy.
    historical = deepcopy(original_payload)
    historical["source_fingerprint_contract"] = "ecology-measurement-candidates-0020"
    assert (
        EcologyMeasurementCandidatesResponse.model_validate(historical).input_sha256
        == original_payload["input_sha256"]
    )

    # Older v0021 artifacts may omit optional row fields that the newer
    # Pydantic schema now supplies as defaults. Hash their persisted rows
    # before those defaults are injected, without claiming a newer review.
    legacy_current = deepcopy(original_payload)
    legacy_current["sampling_date_qc"][0].pop("reused_image_ids")
    legacy_current["candidate_report"] = None
    legacy_hash_payload = {
        "algorithm_version": "ecology-measurement-candidates-0021",
        "project_id": legacy_current["project_id"],
        "registry_history_sha256": legacy_current["source_registry_history_sha256"],
        "registry_image_evidence_sha256": legacy_current["source_image_evidence_sha256"],
        "registry_annotation_evidence_sha256": legacy_current["source_annotation_evidence_sha256"],
        "registry_calibration_evidence_sha256": legacy_current[
            "source_calibration_evidence_sha256"
        ],
        **{
            key: legacy_current[key]
            for key in (
                "candidates",
                "sampling_date_qc",
                "projected_visit_coverage",
                "projected_endpoint_changes",
                "projected_unit_summaries",
                "projected_population_summaries",
                "exclusions",
            )
        },
    }
    legacy_current["input_sha256"] = canonical_json_sha256(legacy_hash_payload)
    assert (
        EcologyMeasurementCandidatesResponse.model_validate(legacy_current).input_sha256
        == legacy_current["input_sha256"]
    )

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
    assert (
        EcologyProjectedEndpointChange.model_validate(original).model_dump(mode="json") == original
    )

    # A previously saved typed result can omit optional later-added slopes.
    legacy = dict(original)
    legacy.pop("projected_absolute_change_per_day")
    legacy.pop("projected_baseline_percent_change_per_day")
    assert (
        EcologyProjectedEndpointChange.model_validate(legacy).projected_absolute_change_per_day
        is None
    )

    # Equivalent offset timestamps must replay the same UTC instants.
    offset = dict(original)
    offset["baseline_capture_timestamp_utc"] = "2026-04-03T04:00:00-04:00"
    offset["final_capture_timestamp_utc"] = "2026-04-05T04:00:00-04:00"
    assert EcologyProjectedEndpointChange.model_validate(offset).elapsed_days == 2

    # Different local calendar dates can still be the same UTC sampling date.
    same_utc_date = dict(original)
    same_utc_date["baseline_capture_timestamp_utc"] = "2026-04-03T23:30:00-04:00"
    same_utc_date["final_capture_timestamp_utc"] = "2026-04-04T00:30:00-04:00"
    with pytest.raises(PydanticValidationError, match="distinct ordered UTC sampling dates"):
        EcologyProjectedEndpointChange.model_validate(same_utc_date)

    # Typed saved-workflow payloads reject changed endpoint calculations
    # even if the attacker keeps all lineage digest strings intact.
    typed_artifact = dict(standalone.json())
    typed_artifact["projected_endpoint_changes"] = [original]
    # A fabricated endpoint cannot be appended to a saved current-contract
    # artifact while retaining the earlier source fingerprint.
    with pytest.raises(PydanticValidationError, match="fingerprint"):
        EcologyMeasurementCandidatesResponse.model_validate(typed_artifact)

    mutations: list[tuple[str, object]] = [
        ("absolute_change", 99.0),
        ("percent_change", 99.0),
        ("elapsed_days", 3.0),
        ("projected_absolute_change_per_day", 99.0),
        ("projected_baseline_percent_change_per_day", 99.0),
        ("baseline_capture_timestamp_utc", "2026-04-03T08:00:00"),
        ("final_capture_timestamp_utc", "2026-04-03T16:00:00Z"),
        ("final_image_id", first.image_id),
        ("baseline_image_id", " "),
        ("final_annotation_evidence_id", ""),
        ("baseline_calibration_evidence_id", " "),
    ]
    for field, replacement in mutations:
        tampered = dict(original)
        tampered[field] = replacement
        with pytest.raises(PydanticValidationError, match="Projected endpoint"):
            EcologyProjectedEndpointChange.model_validate(tampered)
        forged_artifact = dict(typed_artifact)
        forged_artifact["projected_endpoint_changes"] = [tampered]
        with pytest.raises(PydanticValidationError, match=r"fingerprint|Projected endpoint"):
            EcologyMeasurementCandidatesResponse.model_validate(forged_artifact)

    assert original["evidence_level"] == "linked_unverified"
    assert original["review_gate"] == "scientist_review_required"
