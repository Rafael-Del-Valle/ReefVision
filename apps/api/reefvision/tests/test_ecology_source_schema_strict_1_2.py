"""Strict source-linked ecological evidence for API and saved-workflow replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
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


@pytest.mark.parametrize("revision_field", ["identity_revision", "annotation_revision"])
@pytest.mark.parametrize("bad_revision", [True, False, "1", 1.0, None, [], {}])
def test_projected_source_revisions_reject_coerced_identifiers(
    revision_field: str, bad_revision: object
) -> None:
    payload = _candidate_payload()
    payload[revision_field] = bad_revision
    with pytest.raises(SchemaValidationError, match="positive JSON integer"):
        EcologyMeasurementCandidate.model_validate(payload)


@pytest.mark.parametrize("revision_field", ["identity_revision", "annotation_revision"])
@pytest.mark.parametrize("revision", [1, 2, 9])
def test_projected_source_revisions_preserve_valid_positive_integers(
    revision_field: str, revision: int
) -> None:
    payload = _candidate_payload()
    payload[revision_field] = revision
    candidate = EcologyMeasurementCandidate.model_validate(payload)
    assert getattr(candidate, revision_field) == revision


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
def test_linked_measurements_reject_inferred_capture_times(
    bad_timestamp: object,
) -> None:
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


@pytest.mark.parametrize(
    "digest_field",
    ["image_sha256", "annotation_sha256", "calibration_sha256"],
)
@pytest.mark.parametrize(
    "bad_digest",
    ["a" * 63, "a" * 65, "g" * 64, " a" * 32, "\uff41" * 64, None, True, 17, []],
)
def test_projected_evidence_rejects_malformed_sha256(digest_field: str, bad_digest: object) -> None:
    payload = _candidate_payload()
    payload[digest_field] = bad_digest
    with pytest.raises(SchemaValidationError, match="64 hexadecimal"):
        EcologyMeasurementCandidate.model_validate(payload)


def test_projected_evidence_preserves_valid_mixed_case_digest_provenance() -> None:
    payload = _candidate_payload()
    payload["image_sha256"] = "aB" * 32
    payload["annotation_sha256"] = "Cd" * 32
    payload["calibration_sha256"] = "Ef" * 32
    candidate = EcologyMeasurementCandidate.model_validate(payload)
    assert candidate.image_sha256 == "aB" * 32
    assert candidate.annotation_sha256 == "Cd" * 32
    assert candidate.calibration_sha256 == "Ef" * 32


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
        ("identity_revision", True, "positive JSON integer"),
        ("identity_revision", "1", "positive JSON integer"),
        ("annotation_revision", 1.0, "positive JSON integer"),
        ("annotation_revision", None, "positive JSON integer"),
        ("value", "3.2", "JSON number"),
        ("value", True, "JSON number"),
        ("capture_timestamp_utc", 1775203200, "explicit ISO 8601"),
        ("image_sha256", "a" * 63, "64 hexadecimal"),
        ("annotation_sha256", "g" * 64, "64 hexadecimal"),
        ("calibration_sha256", "\uff41" * 64, "64 hexadecimal"),
    ):
        tampered = deepcopy(saved)
        tampered["candidates"][0][field] = bad_value
        if field == "capture_timestamp_utc":
            tampered["candidates"][0]["capture_time_status"] = "timezone_aware"
        with pytest.raises(SchemaValidationError, match=error):
            EcologyMeasurementCandidatesResponse.model_validate(tampered)


def test_saved_identity_registry_rejects_malformed_linked_evidence_hashes(
    client: TestClient,
) -> None:
    """Typed standalone and persisted registry sources must reject forged hash formats.

    These checks validate SHA-256 *syntax*, not the underlying file bytes,
    scientist review, or authenticity of a replacement well-formed digest.
    """
    project_id, _ = _source(client)
    standalone = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert standalone.status_code == 200, standalone.text
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"]
    assert len(artifacts) == 1
    saved = artifacts[0]["payload_json"]
    assert saved == standalone.json()
    parsed = EcologyIdentityRegistryResponse.model_validate(saved)
    assert parsed.evidence_level == "registered_unverified"
    assert parsed.review_gate == "scientist_review_required"

    for collection, field in (
        ("image_evidence_links", "image_sha256"),
        ("annotation_evidence_links", "annotation_sha256"),
        ("calibration_evidence_links", "image_sha256"),
        ("calibration_evidence_links", "calibration_sha256"),
    ):
        assert len(saved[collection]) == 1
        for invalid in ("f" * 63, "g" * 64, True):
            tampered = deepcopy(saved)
            tampered[collection][0][field] = invalid
            with pytest.raises(SchemaValidationError):
                EcologyIdentityRegistryResponse.model_validate(tampered)

        # Case is preserved for historical source provenance; syntax is valid.
        mixed_case = deepcopy(saved)
        mixed_case[collection][0][field] = "aB" * 32
        rehydrated = EcologyIdentityRegistryResponse.model_validate(mixed_case)
        assert getattr(getattr(rehydrated, collection)[0], field) == "aB" * 32


def test_saved_registry_rejects_cross_project_or_orphaned_evidence(
    client: TestClient,
) -> None:
    """A persisted typed source must not mix projects or break provenance joins."""
    project_id, _ = _source(client)
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"]
    assert len(artifacts) == 1
    saved = artifacts[0]["payload_json"]
    assert saved == response.json()
    parsed = EcologyIdentityRegistryResponse.model_validate(saved)
    assert parsed.review_gate == "scientist_review_required"

    for collection in (
        "identities",
        "identity_history",
        "image_evidence_links",
        "annotation_evidence_links",
        "calibration_evidence_links",
    ):
        assert saved[collection]
        tampered = deepcopy(saved)
        tampered[collection][0]["project_id"] = "another-project"
        with pytest.raises(SchemaValidationError, match="cross-project evidence"):
            EcologyIdentityRegistryResponse.model_validate(tampered)

    for collection, field in (
        ("annotation_evidence_links", "image_evidence_id"),
        ("calibration_evidence_links", "annotation_evidence_id"),
    ):
        tampered = deepcopy(saved)
        tampered[collection][0][field] = "missing-evidence-id"
        with pytest.raises(SchemaValidationError, match="orphan"):
            EcologyIdentityRegistryResponse.model_validate(tampered)

    for field in ("image_id", "image_sha256"):
        tampered = deepcopy(saved)
        original = tampered["calibration_evidence_links"][0][field]
        tampered["calibration_evidence_links"][0][field] = (
            "different-image-id"
            if field == "image_id"
            else ("0" if original[0] != "0" else "1") + original[1:]
        )
        with pytest.raises(SchemaValidationError, match="source image mismatch"):
            EcologyIdentityRegistryResponse.model_validate(tampered)

    tampered = deepcopy(saved)
    tampered["image_evidence_links"][0]["identity_revision"] += 10
    with pytest.raises(SchemaValidationError, match="unknown identity revision"):
        EcologyIdentityRegistryResponse.model_validate(tampered)


def test_saved_registry_rejects_forged_counts_and_duplicate_evidence(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"]
    assert len(artifacts) == 1
    saved = artifacts[0]["payload_json"]
    for collection, count_field in (
        ("image_evidence_links", "image_evidence_count"),
        ("annotation_evidence_links", "annotation_evidence_count"),
        ("calibration_evidence_links", "calibration_evidence_count"),
        ("identity_history", "history_revision_count"),
    ):
        tampered = deepcopy(saved)
        tampered[count_field] = len(tampered[collection]) + 1
        with pytest.raises(SchemaValidationError, match="count contradicts"):
            EcologyIdentityRegistryResponse.model_validate(tampered)

    tampered = deepcopy(saved)
    tampered["image_evidence_links"].append(deepcopy(tampered["image_evidence_links"][0]))
    tampered["image_evidence_count"] += 1
    with pytest.raises(SchemaValidationError, match="duplicate evidence identities"):
        EcologyIdentityRegistryResponse.model_validate(tampered)
