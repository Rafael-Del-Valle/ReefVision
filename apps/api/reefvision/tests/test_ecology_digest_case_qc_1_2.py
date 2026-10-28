"""Case-insensitive source-image SHA-256 QC and saved-artifact regression."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_endpoint_changes,
    summarize_sampling_date_qc,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def _candidate(
    organism: str,
    image_id: str,
    digest: str,
    captured: datetime | None,
    *,
    status: str = "timezone_aware",
) -> EcologyMeasurementCandidate:
    return EcologyMeasurementCandidate.model_validate(
        {
            "organism_key": organism,
            "identity_revision": 1,
            "parent_colony_key": "parent-A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "image_id": image_id,
            "image_sha256": digest,
            "annotation_evidence_id": f"evidence-{organism}-{image_id}",
            "calibration_evidence_id": f"calibration-{image_id}",
            "annotation_kind": "box",
            "annotation_id": f"annotation-{organism}-{image_id}",
            "annotation_revision": 1,
            "annotation_sha256": "b" * 64,
            "calibration_sha256": "c" * 64,
            "metric": "box_width",
            "value": 5.0,
            "unit": "mm",
            "capture_timestamp_utc": captured,
            "capture_time_status": status,
        }
    )


def _two_series() -> list[EcologyMeasurementCandidate]:
    first = datetime(2026, 4, 3, 8, tzinfo=UTC)
    final = datetime(2026, 4, 4, 8, tzinfo=UTC)
    return [
        _candidate("A", "A-first", "a" * 64, first),
        _candidate("A", "A-last", "c" * 64, final),
        _candidate("B", "B-first", "b" * 64, first),
        _candidate("B", "B-last", "d" * 64, final),
    ]


def test_uppercase_reimport_across_dates_excludes_both_organisms() -> None:
    candidates = _two_series()
    candidates[-1] = candidates[-1].model_copy(update={"image_sha256": "A" * 64})
    qc = summarize_sampling_date_qc(candidates)
    assert [row.qc_status for row in qc] == [
        "reused_image_content_across_dates",
        "reused_image_content_across_dates",
    ]
    assert all(row.reused_image_sha256 == ["a" * 64] for row in qc)
    assert summarize_sampling_date_qc(list(reversed(candidates))) == qc
    assert summarize_projected_endpoint_changes(candidates, qc) == []


def test_uppercase_same_photo_same_instant_is_not_a_false_conflict() -> None:
    candidates = _two_series()
    # Both organisms appear in one source photograph, imported under
    # different IDs and equivalent local/UTC acquisition timestamps.
    candidates[2] = candidates[2].model_copy(
        update={
            "image_sha256": "A" * 64,
            "capture_timestamp_utc": datetime(2026, 4, 3, 4, tzinfo=timezone(-timedelta(hours=4))),
        }
    )
    qc = summarize_sampling_date_qc(candidates)
    assert [row.qc_status for row in qc] == [
        "date_series_candidate",
        "date_series_candidate",
    ]
    assert len(summarize_projected_endpoint_changes(candidates, qc)) == 2

    # A second organism may reference the exact same image ID; hex casing
    # alone must not forge a source-image metadata disagreement.
    candidates[2] = candidates[2].model_copy(update={"image_id": "A-first"})
    assert all(
        row.qc_status == "date_series_candidate" for row in summarize_sampling_date_qc(candidates)
    )


def test_uppercase_undated_reimport_cannot_borrow_dated_photo() -> None:
    candidates = _two_series()
    candidates[2] = candidates[2].model_copy(
        update={
            "image_sha256": "A" * 64,
            "capture_timestamp_utc": None,
            "capture_time_status": "timezone_missing",
        }
    )
    qc = summarize_sampling_date_qc(candidates)
    assert [row.qc_status for row in qc] == [
        "source_capture_conflict",
        "source_capture_conflict",
    ]
    assert all(row.conflicting_source_image_sha256 == ["a" * 64] for row in qc)
    assert summarize_projected_endpoint_changes(candidates, qc) == []


def test_saved_workflow_source_artifact_replay_retains_digest_qc(
    client: TestClient,
) -> None:
    """Run a saved workflow, then rehydrate its source schema before QC."""
    project_id, _ = _source(client)
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    saved = EcologyMeasurementCandidatesResponse.model_validate(artifacts[0]["payload_json"])
    assert saved.candidates
    source = saved.candidates[0]
    candidates = _two_series()
    candidates[0] = candidates[0].model_copy(update={"image_sha256": source.image_sha256})
    candidates[-1] = candidates[-1].model_copy(update={"image_sha256": source.image_sha256.upper()})
    restored = [
        EcologyMeasurementCandidate.model_validate(row.model_dump(mode="json"))
        for row in candidates
    ]
    qc = summarize_sampling_date_qc(restored)
    assert all(row.qc_status == "reused_image_content_across_dates" for row in qc)
    assert summarize_projected_endpoint_changes(restored, qc) == []
    assert restored[-1].image_sha256 == source.image_sha256.upper()
    assert all(row.review_gate == "scientist_review_required" for row in restored)
