"""Standalone and saved Workflow Builder parity for projected ecological evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyProjectedUnitSummary,
    EcologySamplingDateQC,
)
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_endpoint_changes,
    summarize_projected_population_summaries,
    summarize_projected_unit_summaries,
    summarize_sampling_date_qc,
)
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _get(client: TestClient, project_id: str):
    return client.get(f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates")


def test_projected_box_candidates_are_typed_unverified_and_saved(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    response = _get(client, project_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidate_count"] == 2
    assert payload["evidence_level"] == "linked_unverified"
    assert payload["review_gate"] == "scientist_review_required"
    assert {row["metric"]: row["value"] for row in payload["candidates"]} == {
        "box_width": 6.25,
        "box_height": 5.0,
    }
    assert {row["unit"] for row in payload["candidates"]} == {"mm"}
    assert all(row["capture_time_status"] == "missing" for row in payload["candidates"])
    assert all(row["capture_timestamp_utc"] is None for row in payload["candidates"])
    assert len(payload["input_sha256"]) == 64
    assert len(payload["sampling_date_qc"]) == 2
    assert all(row["qc_status"] == "missing_timestamps" for row in payload["sampling_date_qc"])
    assert all(row["reused_image_ids"] == [] for row in payload["sampling_date_qc"])
    assert all(row["reused_image_sha256"] == [] for row in payload["sampling_date_qc"])
    assert all(row["conflicting_source_image_ids"] == [] for row in payload["sampling_date_qc"])
    assert all(row["conflicting_source_image_sha256"] == [] for row in payload["sampling_date_qc"])
    assert all(
        row["review_gate"] == "scientist_review_required" for row in payload["sampling_date_qc"]
    )
    assert payload["projected_endpoint_changes"] == []
    assert len(payload["projected_unit_summaries"]) == 2
    assert payload["projected_population_summaries"] == []
    assert all(
        row["unit_status"] == "missing_unit_declaration"
        for row in payload["projected_unit_summaries"]
    )

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(
        item for item in registry.json() if item["node_type"] == "ecology_identity_registry_source"
    )
    assert any(
        port["port_id"] == "measurement_candidates"
        and port["accepted_types"] == ["ecology_measurement_candidates"]
        for port in node["output_ports"]
    )
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        item
        for item in workflow["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload


def test_source_change_revokes_candidate_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    assert _get(client, project_id).status_code == 200
    _save_calibration(client, image_id, scale=0.5)
    assert _get(client, project_id).status_code == 400
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert not any(
        row["data_type"] == "ecology_measurement_candidates" for row in workflow["artifacts"]
    )


def test_perspective_transform_is_explicitly_excluded_not_scaled(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        metadata = dict(image.metadata_json or {})
        saved = dict(metadata["measurement_calibration"])
        saved["perspective_homography"] = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        metadata["measurement_calibration"] = saved
        image.metadata_json = metadata
        session.commit()
    assert _link_calibration(client, project_id, annotation).status_code == 201
    payload = _get(client, project_id).json()
    assert payload["candidate_count"] == 0
    assert payload["exclusions"][0]["reason"] == "perspective_transform_requires_review"
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload


def test_identity_revision_invalidates_old_measurement_evidence_and_saved_workflow(
    client: TestClient,
) -> None:
    """An identity correction must not silently reassign old source geometry."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    before = _get(client, project_id)
    assert before.status_code == 200, before.text
    assert before.json()["candidate_count"] == 2

    # Historical image evidence is bound to revision 1. Assigning the colony
    # to a tank in revision 2 cannot retroactively label that image as a
    # tank-A measurement without a new scientist-reviewed evidence decision.
    revised = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/colony-a/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "parent_colony_key": None,
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "reason": "Corrected experimental unit after specimen review",
        },
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["revision"] == 2

    response = _get(client, project_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidate_count"] == 0
    assert payload["candidates"] == []
    assert payload["sampling_date_qc"] == []
    assert payload["projected_endpoint_changes"] == []
    assert payload["projected_unit_summaries"] == []
    assert payload["projected_population_summaries"] == []
    assert len(payload["exclusions"]) == 1
    assert payload["exclusions"][0]["reason"] == "identity_revision_requires_review"
    assert payload["input_sha256"] != before.json()["input_sha256"]
    assert payload["evidence_level"] == "linked_unverified"
    assert payload["review_gate"] == "scientist_review_required"

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    snapshot = registry.json()
    assert snapshot["identities"][0]["revision"] == 2
    assert snapshot["image_evidence_links"][0]["identity_revision"] == 1

    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload


def test_utc_date_qc_rejects_replicates_missing_dates_and_mixed_units(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    candidate = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    first = candidate.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    second = first.model_copy(
        update={
            "image_id": "second-source-image",
            "image_sha256": "1" * 64,
            "capture_timestamp_utc": datetime(2026, 4, 4, 9, tzinfo=UTC),
        }
    )
    ready = summarize_sampling_date_qc([second, first])[0]
    assert ready.qc_status == "date_series_candidate"
    assert ready.sampling_dates_utc == ["2026-04-03", "2026-04-04"]
    assert ready.candidate_count == 2
    assert ready.review_gate == "scientist_review_required"
    assert summarize_sampling_date_qc([first])[0].qc_status == "insufficient_dates"

    same_day = second.model_copy(
        update={"capture_timestamp_utc": datetime(2026, 4, 3, 11, tzinfo=UTC)}
    )
    duplicate = summarize_sampling_date_qc([first, same_day])[0]
    assert duplicate.qc_status == "same_day_technical_replicates"
    assert duplicate.duplicate_sampling_dates_utc == ["2026-04-03"]

    missing = second.model_copy(
        update={"capture_timestamp_utc": None, "capture_time_status": "missing"}
    )
    missing_qc = summarize_sampling_date_qc([first, missing])[0]
    assert missing_qc.qc_status == "missing_timestamps"
    assert missing_qc.missing_timestamp_image_ids == ["second-source-image"]
    mixed = second.model_copy(update={"unit": "cm"})
    assert summarize_sampling_date_qc([first, mixed])[0].qc_status == "mixed_units"

    # Local capture dates differ, but both must be normalized to UTC first.
    local_time = second.model_copy(
        update={
            "capture_timestamp_utc": datetime(
                2026, 4, 3, 23, 30, tzinfo=timezone(-timedelta(hours=5))
            )
        }
    )
    assert summarize_sampling_date_qc([first, local_time])[0].qc_status == ("date_series_candidate")


def test_reused_image_across_dates_cannot_become_projected_growth(
    client: TestClient,
) -> None:
    """The same photograph cannot represent two biological observation days."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    source = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    baseline = source.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    # A forged timestamp cannot turn a reused image into longitudinal evidence.
    replayed = baseline.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": baseline.value + 1,
        }
    )
    qc = summarize_sampling_date_qc([baseline, replayed])
    assert len(qc) == 1
    assert qc[0].qc_status == "reused_image_across_dates"
    assert qc[0].reused_image_ids == [baseline.image_id]
    assert qc[0].review_gate == "scientist_review_required"
    assert summarize_projected_endpoint_changes([baseline, replayed], qc) == []

    # A reimported copy has a different database ID but identical image bytes.
    # It must not create a second biological observation date.
    reimported = replayed.model_copy(update={"image_id": "reimported-photo"})
    content_qc = summarize_sampling_date_qc([baseline, reimported])
    assert content_qc[0].qc_status == "reused_image_content_across_dates"
    assert content_qc[0].reused_image_ids == []
    assert content_qc[0].reused_image_sha256 == [baseline.image_sha256]
    assert content_qc[0].review_gate == "scientist_review_required"
    assert summarize_projected_endpoint_changes([baseline, reimported], content_qc) == []

    # Legacy persisted QC records deserialize without the newly added field.
    legacy = qc[0].model_dump(mode="json")
    legacy.pop("reused_image_ids")
    legacy.pop("reused_image_sha256")
    legacy.pop("conflicting_source_image_ids")
    legacy.pop("conflicting_source_image_sha256")
    legacy_qc = EcologySamplingDateQC.model_validate(legacy)
    assert legacy_qc.reused_image_ids == []
    assert legacy_qc.reused_image_sha256 == []
    assert legacy_qc.conflicting_source_image_ids == []
    assert legacy_qc.conflicting_source_image_sha256 == []

    # A distinct photographed image can still enter a provisional date series.
    distinct = replayed.model_copy(
        update={"image_id": "distinct-followup-image", "image_sha256": "2" * 64}
    )
    distinct_qc = summarize_sampling_date_qc([baseline, distinct])
    assert distinct_qc[0].qc_status == "date_series_candidate"
    assert distinct_qc[0].reused_image_ids == []
    assert distinct_qc[0].reused_image_sha256 == []
    changes = summarize_projected_endpoint_changes([baseline, distinct], distinct_qc)
    assert len(changes) == 1
    assert changes[0].review_gate == "scientist_review_required"


def test_cross_series_source_replay_cannot_create_projected_growth(
    client: TestClient,
) -> None:
    """Reimported photographs must not migrate between biological date series."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    source = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    first = source.model_copy(
        update={
            "organism_key": "organism-A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "parent_colony_key": "parent-A",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    last = first.model_copy(
        update={
            "image_id": "A-followup",
            "image_sha256": "a" * 64,
            "annotation_evidence_id": "A-followup-annotation",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": first.value + 1,
        }
    )
    other_first = first.model_copy(
        update={
            "organism_key": "organism-B",
            "image_id": "B-baseline",
            "image_sha256": "b" * 64,
            "annotation_evidence_id": "B-baseline-annotation",
        }
    )
    other_last = other_first.model_copy(
        update={
            "image_id": "B-followup",
            "image_sha256": "c" * 64,
            "annotation_evidence_id": "B-followup-annotation",
            "capture_timestamp_utc": datetime(2026, 4, 4, 9, tzinfo=UTC),
            "value": other_first.value + 2,
        }
    )
    clean = [first, last, other_first, other_last]
    clean_qc = summarize_sampling_date_qc(clean)
    assert [row.qc_status for row in clean_qc] == [
        "date_series_candidate",
        "date_series_candidate",
    ]
    clean_changes = summarize_projected_endpoint_changes(clean, clean_qc)
    assert len(clean_changes) == 2
    assert summarize_projected_unit_summaries(clean, clean_changes)[0].unit_status == ("candidate")

    # Reimported bytes in a different organism's later observation bypass
    # per-organism checks, but must invalidate *both* affected date series.
    replayed = [
        first,
        last,
        other_first,
        other_last.model_copy(update={"image_sha256": first.image_sha256}),
    ]
    replay_qc = summarize_sampling_date_qc(replayed)
    assert [row.qc_status for row in replay_qc] == [
        "reused_image_content_across_dates",
        "reused_image_content_across_dates",
    ]
    assert all(row.reused_image_sha256 == [first.image_sha256] for row in replay_qc)
    assert all(row.review_gate == "scientist_review_required" for row in replay_qc)
    assert summarize_sampling_date_qc(list(reversed(replayed))) == replay_qc
    assert summarize_projected_endpoint_changes(replayed, replay_qc) == []
    assert summarize_projected_unit_summaries(replayed, [])[0].unit_status == (
        "incomplete_followup"
    )
    with pytest.raises(ValidationError, match="sampling-date QC does not match"):
        summarize_projected_endpoint_changes(replayed, clean_qc)

    # The same source image ID assigned to two dates is likewise blocked,
    # even when its records belong to different organisms.
    reused_id = [
        first,
        last,
        other_first,
        other_last.model_copy(update={"image_id": first.image_id}),
    ]
    assert all(
        row.qc_status == "reused_image_across_dates"
        for row in summarize_sampling_date_qc(reused_id)
    )

    # One legitimate photograph can contain two organisms on the SAME date.
    same_day_shared = [
        first,
        last,
        other_first.model_copy(update={"image_sha256": first.image_sha256}),
        other_last,
    ]
    assert all(
        row.qc_status == "date_series_candidate"
        for row in summarize_sampling_date_qc(same_day_shared)
    )


def test_undated_reimport_cannot_borrow_a_dated_photographs_provenance(
    client: TestClient,
) -> None:
    """Identical bytes with unknown and known acquisition times need review."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    source = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    first = source.model_copy(
        update={
            "organism_key": "organism-A",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    last = first.model_copy(
        update={
            "image_id": "A-followup",
            "image_sha256": "a" * 64,
            "annotation_evidence_id": "A-followup-annotation",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": first.value + 1,
        }
    )
    # Reimported source bytes under a new image ID, with the acquisition
    # timestamp lost. They cannot silently borrow the dated copy's time.
    unknown = first.model_copy(
        update={
            "organism_key": "organism-B",
            "image_id": "B-baseline",
            "annotation_evidence_id": "B-baseline-annotation",
            "capture_timestamp_utc": None,
            "capture_time_status": "missing",
        }
    )
    other_last = unknown.model_copy(
        update={
            "image_id": "B-followup",
            "image_sha256": "b" * 64,
            "annotation_evidence_id": "B-followup-annotation",
            "capture_timestamp_utc": datetime(2026, 4, 4, 9, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    conflicting = [first, last, unknown, other_last]
    qc = summarize_sampling_date_qc(conflicting)
    assert [row.qc_status for row in qc] == [
        "source_capture_conflict",
        "source_capture_conflict",
    ]
    assert all(row.conflicting_source_image_sha256 == [first.image_sha256] for row in qc)
    assert all(row.review_gate == "scientist_review_required" for row in qc)
    assert summarize_sampling_date_qc(list(reversed(conflicting))) == qc
    assert summarize_projected_endpoint_changes(conflicting, qc) == []
    assert all(
        row.unit_status != "candidate"
        for row in summarize_projected_unit_summaries(conflicting, [])
    )
    # A naive timestamp is not evidence of the UTC acquisition instant.
    naive = unknown.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8),
            "capture_time_status": "timezone_missing",
        }
    )
    naive_qc = summarize_sampling_date_qc([first, last, naive, other_last])
    assert all(row.qc_status == "source_capture_conflict" for row in naive_qc)
    assert summarize_projected_endpoint_changes([first, last, naive, other_last], naive_qc) == []

    # A matching, timezone-aware instant on the reimport is legitimate:
    # the same photograph may contain multiple organisms on one UTC date.
    restored = unknown.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 4, tzinfo=timezone(timedelta(hours=-4))),
            "capture_time_status": "timezone_aware",
        }
    )
    valid = [first, last, restored, other_last]
    assert all(
        row.qc_status == "date_series_candidate" for row in summarize_sampling_date_qc(valid)
    )
    assert len(summarize_projected_endpoint_changes(valid, summarize_sampling_date_qc(valid))) == 2


def test_same_day_source_capture_conflicts_exclude_all_affected_series(
    client: TestClient,
) -> None:
    """One photograph cannot carry inconsistent timestamps or bytes."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    source = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    baseline = source.model_copy(
        update={
            "organism_key": "organism-A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    followup = baseline.model_copy(
        update={
            "image_id": "A-followup",
            "image_sha256": "a" * 64,
            "annotation_evidence_id": "A-followup-evidence",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": baseline.value + 1,
        }
    )
    other_baseline = baseline.model_copy(
        update={
            "organism_key": "organism-B",
            "image_id": "B-baseline",
            "annotation_evidence_id": "B-baseline-evidence",
        }
    )
    other_followup = other_baseline.model_copy(
        update={
            "image_id": "B-followup",
            "image_sha256": "b" * 64,
            "annotation_evidence_id": "B-followup-evidence",
            "capture_timestamp_utc": datetime(2026, 4, 4, 9, tzinfo=UTC),
            "value": other_baseline.value + 2,
        }
    )
    clean = [baseline, followup, other_baseline, other_followup]
    assert all(
        row.qc_status == "date_series_candidate" for row in summarize_sampling_date_qc(clean)
    )

    # Identical bytes with two *different* acquisition instants on the same
    # UTC date must invalidate both organisms, even with different image IDs.
    shifted = other_baseline.model_copy(
        update={"capture_timestamp_utc": datetime(2026, 4, 3, 9, tzinfo=UTC)}
    )
    conflicting = [baseline, followup, shifted, other_followup]
    qc = summarize_sampling_date_qc(conflicting)
    assert [row.qc_status for row in qc] == [
        "source_capture_conflict",
        "source_capture_conflict",
    ]
    assert all(row.conflicting_source_image_sha256 == [baseline.image_sha256] for row in qc)
    assert summarize_sampling_date_qc(list(reversed(conflicting))) == qc
    assert summarize_projected_endpoint_changes(conflicting, qc) == []
    assert all(
        row.unit_status == "incomplete_followup"
        for row in summarize_projected_unit_summaries(conflicting, [])
    )
    with pytest.raises(ValidationError, match="sampling-date QC does not match"):
        summarize_projected_endpoint_changes(conflicting, summarize_sampling_date_qc(clean))

    # An image ID cannot point to different bytes, even with an identical
    # timestamp. No duplicate biological sampling date is required to fail.
    altered_id = other_baseline.model_copy(
        update={"image_id": baseline.image_id, "image_sha256": "c" * 64}
    )
    inconsistent = [baseline, followup, altered_id, other_followup]
    id_qc = summarize_sampling_date_qc(inconsistent)
    assert [row.qc_status for row in id_qc] == [
        "source_capture_conflict",
        "source_capture_conflict",
    ]
    assert all(row.conflicting_source_image_ids == [baseline.image_id] for row in id_qc)
    assert summarize_projected_endpoint_changes(inconsistent, id_qc) == []

    # Different local offsets representing the SAME UTC instant are valid.
    offset_equivalent = other_baseline.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 4, tzinfo=timezone(timedelta(hours=-4)))
        }
    )
    valid = [baseline, followup, offset_equivalent, other_followup]
    assert all(
        row.qc_status == "date_series_candidate" for row in summarize_sampling_date_qc(valid)
    )
    assert len(summarize_projected_endpoint_changes(valid, summarize_sampling_date_qc(valid))) == 2


def test_source_linked_projected_endpoint_change_is_not_verified_growth(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    candidate = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    baseline = candidate.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    final = baseline.model_copy(
        update={
            "image_id": "different-image",
            "image_sha256": "3" * 64,
            "annotation_evidence_id": "different-annotation-evidence",
            "calibration_evidence_id": "different-calibration-evidence",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": baseline.value + 2.5,
        }
    )
    qc = summarize_sampling_date_qc([final, baseline])
    assert qc[0].qc_status == "date_series_candidate"
    changes = summarize_projected_endpoint_changes([final, baseline], qc)
    assert len(changes) == 1
    change = changes[0]
    assert change.absolute_change == 2.5
    assert change.baseline_value == 5.0
    assert change.percent_change == pytest.approx(50.0)
    assert change.elapsed_days == 1.0
    assert change.projected_absolute_change_per_day == pytest.approx(2.5)
    assert change.projected_baseline_percent_change_per_day == pytest.approx(50.0)
    assert change.observed_timepoint_count == 2
    assert change.baseline_image_id == baseline.image_id
    assert change.final_image_id == "different-image"
    assert change.evidence_level == "linked_unverified"
    assert change.review_gate == "scientist_review_required"

    # Slopes divide by actual elapsed UTC hours, not the number of calendar
    # dates or an assumed one-day interval; this is not biological growth.
    delayed = final.model_copy(
        update={"capture_timestamp_utc": datetime(2026, 4, 6, 8, tzinfo=UTC)}
    )
    delayed_change = summarize_projected_endpoint_changes(
        [baseline, delayed], summarize_sampling_date_qc([baseline, delayed])
    )[0]
    assert delayed_change.elapsed_days == 3.0
    assert delayed_change.projected_absolute_change_per_day == pytest.approx(2.5 / 3)
    assert delayed_change.projected_baseline_percent_change_per_day == pytest.approx(50 / 3)
    assert delayed_change.review_gate == "scientist_review_required"

    # Previously persisted typed workflow artifacts remain readable.
    legacy = change.model_dump(mode="json")
    legacy.pop("projected_absolute_change_per_day")
    legacy.pop("projected_baseline_percent_change_per_day")
    assert type(change).model_validate(legacy).projected_absolute_change_per_day is None

    # A near-zero positive elapsed interval can overflow an otherwise finite
    # geometric difference. It must fail closed, never persist Infinity.
    huge_start = baseline.model_copy(
        update={
            "value": 1e300,
            "capture_timestamp_utc": datetime(2026, 4, 3, 23, 59, 59, 999999, tzinfo=UTC),
        }
    )
    huge_end = final.model_copy(
        update={
            "value": 1.1e300,
            "capture_timestamp_utc": datetime(2026, 4, 4, 0, 0, tzinfo=UTC),
        }
    )
    with pytest.raises(ValidationError, match="nonfinite or unordered"):
        summarize_projected_endpoint_changes(
            [huge_start, huge_end], summarize_sampling_date_qc([huge_start, huge_end])
        )

    # A revision or declared independent-unit change cannot become growth.
    revised = final.model_copy(update={"identity_revision": 2})
    revised_qc = summarize_sampling_date_qc([baseline, revised])
    assert revised_qc[0].qc_status == "identity_context_changed"
    assert summarize_projected_endpoint_changes([baseline, revised], revised_qc) == []
    moved_unit = final.model_copy(update={"experimental_unit_id": "other-tank"})
    moved_qc = summarize_sampling_date_qc([baseline, moved_unit])
    assert moved_qc[0].qc_status == "identity_context_changed"
    assert summarize_projected_endpoint_changes([baseline, moved_unit], moved_qc) == []

    same_day = final.model_copy(
        update={"capture_timestamp_utc": datetime(2026, 4, 3, 11, tzinfo=UTC)}
    )
    duplicate_qc = summarize_sampling_date_qc([baseline, same_day])
    assert duplicate_qc[0].qc_status == "same_day_technical_replicates"
    assert summarize_projected_endpoint_changes([baseline, same_day], duplicate_qc) == []


def test_projected_endpoint_rechecks_qc_against_current_sources(
    client: TestClient,
) -> None:
    """Stale review decisions cannot turn changed sources into growth."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    width = next(
        EcologyMeasurementCandidate.model_validate(row)
        for row in _get(client, project_id).json()["candidates"]
        if row["metric"] == "box_width"
    )
    baseline = width.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    final = baseline.model_copy(
        update={
            "image_id": "later-width-image",
            "image_sha256": "4" * 64,
            "annotation_evidence_id": "later-width-annotation",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": baseline.value + 2.5,
        }
    )
    qc = summarize_sampling_date_qc([baseline, final])
    changes = summarize_projected_endpoint_changes([baseline, final], qc)
    assert len(changes) == 1
    assert changes[0].baseline_value == 6.25
    assert changes[0].absolute_change == 2.5
    assert changes[0].percent_change == pytest.approx(40.0)

    # Each change invalidates the previously computed date/identity/unit QC.
    changed_sources = [
        final.model_copy(update={"capture_timestamp_utc": datetime(2026, 4, 3, 12, tzinfo=UTC)}),
        final.model_copy(update={"identity_revision": baseline.identity_revision + 1}),
        final.model_copy(update={"unit": "cm"}),
        final.model_copy(update={"image_sha256": baseline.image_sha256}),
    ]
    for changed in changed_sources:
        with pytest.raises(ValidationError, match="sampling-date QC does not match"):
            summarize_projected_endpoint_changes([baseline, changed], qc)

    forged = qc[0].model_copy(update={"source_image_ids": ["unlinked-image"]})
    with pytest.raises(ValidationError, match="sampling-date QC does not match"):
        summarize_projected_endpoint_changes([baseline, final], [forged])
    with pytest.raises(ValidationError, match="sampling-date QC does not match"):
        summarize_projected_endpoint_changes([baseline, final], qc + qc)


def test_projected_unit_qc_excludes_incomplete_and_technical_replicates(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    source = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    first = source.model_copy(
        update={
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "parent_colony_key": "parent-A",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    last = first.model_copy(
        update={
            "image_id": "A-later",
            "image_sha256": "5" * 64,
            "annotation_evidence_id": "annotation-A-later",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": first.value + 2.5,
        }
    )
    second_first = first.model_copy(
        update={
            "organism_key": "organism-B",
            "parent_colony_key": "parent-B",
            "image_id": "B-earlier",
            "image_sha256": "6" * 64,
            "annotation_evidence_id": "annotation-B-earlier",
            "value": 4.0,
        }
    )
    second_last = second_first.model_copy(
        update={
            "image_id": "B-later",
            "image_sha256": "7" * 64,
            "annotation_evidence_id": "annotation-B-later",
            "capture_timestamp_utc": datetime(2026, 4, 4, 9, tzinfo=UTC),
            "value": 5.0,
        }
    )

    def summarize(rows: list[EcologyMeasurementCandidate]):
        changes = summarize_projected_endpoint_changes(rows, summarize_sampling_date_qc(rows))
        return summarize_projected_unit_summaries(rows, changes)[0]

    full = [first, last, second_first, second_last]
    unit = summarize(full)
    assert unit.unit_status == "candidate"
    assert len(unit.organism_keys) == 2
    assert unit.mean_absolute_change == 1.75
    assert unit.parent_colony_keys == ["parent-A", "parent-B"]
    assert unit.review_gate == "scientist_review_required"

    incomplete = summarize([first, last, second_first])
    assert incomplete.unit_status == "incomplete_followup"
    assert incomplete.incomplete_organism_keys == ["organism-B"]
    assert incomplete.mean_absolute_change is None

    delayed = second_last.model_copy(
        update={"capture_timestamp_utc": datetime(2026, 4, 5, 9, tzinfo=UTC)}
    )
    assert summarize([first, last, second_first, delayed]).unit_status == "sampling_window_mismatch"
    technical = [row.model_copy(update={"experimental_unit_type": "video_frame"}) for row in full]
    assert summarize(technical).unit_status == "technical_replicate_unit"
    assert summarize(technical).mean_absolute_change is None

    # The unit-level aggregator must not accept stale, missing or edited
    # endpoint results as if they were derived from the current source rows.
    changes = summarize_projected_endpoint_changes(full, summarize_sampling_date_qc(full))
    invalid_change_sets = [
        changes[:-1],
        [changes[0].model_copy(update={"absolute_change": 999.0}), *changes[1:]],
        [
            changes[0].model_copy(update={"baseline_image_id": "stale-image"}),
            *changes[1:],
        ],
    ]
    for altered in invalid_change_sets:
        with pytest.raises(ValidationError, match="do not match source candidates"):
            summarize_projected_unit_summaries(full, altered)


def test_projected_unit_rejects_cross_metric_identity_and_unit_conflicts(
    client: TestClient,
) -> None:
    """A specimen cannot silently change colony, revision or tank by metric."""
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    source = EcologyMeasurementCandidate.model_validate(
        _get(client, project_id).json()["candidates"][0]
    )
    baseline = source.model_copy(
        update={
            "metric": "box_width",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "parent_colony_key": "parent-A",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    final = baseline.model_copy(
        update={
            "image_id": "followup",
            "image_sha256": "8" * 64,
            "annotation_evidence_id": "followup-annotation",
            "capture_timestamp_utc": datetime(2026, 4, 4, 8, tzinfo=UTC),
            "value": baseline.value + 1,
        }
    )
    width = [baseline, final]

    def unit_summaries(
        rows: list[EcologyMeasurementCandidate],
    ) -> list[EcologyProjectedUnitSummary]:
        qc = summarize_sampling_date_qc(rows)
        changes = summarize_projected_endpoint_changes(rows, qc)
        return summarize_projected_unit_summaries(rows, changes)

    height = [row.model_copy(update={"metric": "box_height"}) for row in width]
    assert len(unit_summaries(width + height)) == 2
    for changed_context in (
        {"experimental_unit_id": "tank-B"},
        {"parent_colony_key": "parent-B"},
        {"identity_revision": baseline.identity_revision + 1},
    ):
        changed_height = [
            row.model_copy(update={"metric": "box_height", **changed_context}) for row in width
        ]
        # Each metric independently passes date QC; the conflict is visible
        # only when the same organism is reconciled across metric types.
        assert all(
            row.qc_status == "date_series_candidate"
            for row in summarize_sampling_date_qc(width + changed_height)
        )
        with pytest.raises(ValidationError, match="changed across metrics"):
            unit_summaries(width + changed_height)


def test_projected_population_is_unit_weighted_and_stratified() -> None:
    tank_a = EcologyProjectedUnitSummary(
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
        metric="box_width",
        units=["mm"],
        organism_keys=["A1", "A2", "A3"],
        complete_organism_keys=["A1", "A2", "A3"],
        incomplete_organism_keys=[],
        parent_colony_keys=["colony-1"],
        sampling_windows_utc=["2026-04-03/2026-04-04"],
        unit_status="candidate",
        mean_absolute_change=1.0,
        mean_percent_change=10.0,
    )
    tank_b = tank_a.model_copy(
        update={
            "experimental_unit_id": "tank-B",
            "organism_keys": ["B1"],
            "complete_organism_keys": ["B1"],
            "mean_absolute_change": 9.0,
            "mean_percent_change": 90.0,
        }
    )
    summaries = summarize_projected_population_summaries([tank_b, tank_a])
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.experimental_unit_ids == ["tank-A", "tank-B"]
    assert summary.declared_unit_count == 2
    assert summary.contributing_organism_count == 4
    assert summary.mean_unit_absolute_change == 5.0
    assert summary.mean_unit_percent_change == 50.0
    assert summary.sample_sd_unit_absolute_change == pytest.approx(5.656854249492381)
    assert summary.sample_sd_unit_percent_change == pytest.approx(56.568542494923804)
    assert summary.shared_parent_colony_keys == ["colony-1"]
    assert summary.design_review_blockers == [
        "independence_not_authenticated",
        "shared_parent_colonies",
    ]
    assert summary.independent_unit_inference_allowed is False
    assert summary.evidence_level == "linked_unverified"
    assert summary.review_gate == "scientist_review_required"

    incomplete = tank_b.model_copy(
        update={
            "unit_status": "incomplete_followup",
            "mean_absolute_change": None,
            "mean_percent_change": None,
        }
    )
    eligible = summarize_projected_population_summaries([tank_a, incomplete])
    assert len(eligible) == 1
    assert eligible[0].experimental_unit_ids == ["tank-A"]
    assert eligible[0].sample_sd_unit_absolute_change is None
    assert eligible[0].sample_sd_unit_percent_change is None
    assert eligible[0].design_review_blockers == [
        "independence_not_authenticated",
        "single_declared_unit",
    ]

    later = tank_b.model_copy(update={"sampling_windows_utc": ["2026-04-03/2026-04-05"]})
    assert len(summarize_projected_population_summaries([tank_a, later])) == 2
    other_unit = tank_b.model_copy(update={"units": ["cm"]})
    assert len(summarize_projected_population_summaries([tank_a, other_unit])) == 2
    other_design = tank_b.model_copy(update={"experimental_unit_type": "colony"})
    assert len(summarize_projected_population_summaries([tank_a, other_design])) == 2
    no_parent = tank_b.model_copy(update={"parent_colony_keys": []})
    parent_qc = summarize_projected_population_summaries([tank_a, no_parent])[0]
    assert parent_qc.units_missing_parent_colony == ["tank-B"]
    technical = tank_b.model_copy(update={"unit_status": "technical_replicate_unit"})
    assert summarize_projected_population_summaries([technical]) == []

    # A single tank/metric must not masquerade as two independent records
    # merely because its reported sampling window or physical unit differs.
    repeated_window = tank_a.model_copy(update={"sampling_windows_utc": ["2026-04-03/2026-04-05"]})
    repeated_unit = tank_a.model_copy(update={"units": ["cm"]})
    for duplicated in (repeated_window, repeated_unit, tank_a):
        with pytest.raises(ValidationError, match="Duplicate projected experimental-unit"):
            summarize_projected_population_summaries([tank_a, duplicated])

    # Invalid organism coverage must never inflate the biological denominator.
    for coverage in (["A1", "A2"], ["A1", "A2", "A2", "A3"], ["A1", "A2", "A3", "A3"]):
        inflated = tank_a.model_copy(update={"complete_organism_keys": coverage})
        with pytest.raises(ValidationError, match="organism coverage is inconsistent"):
            summarize_projected_population_summaries([inflated])

    # Repeating a parent within one unit must not manufacture a shared
    # parent-colony finding or corrupt the lineage audit.
    repeated_parent = tank_a.model_copy(update={"parent_colony_keys": ["colony-1", "colony-1"]})
    with pytest.raises(ValidationError, match="parent-colony provenance is inconsistent"):
        summarize_projected_population_summaries([repeated_parent])

    # A row marked eligible must not slip into population statistics with
    # missing means, even when an unchecked model_copy supplies the values.
    for field in ("mean_absolute_change", "mean_percent_change"):
        invalid = tank_b.model_copy(update={field: None})
        with pytest.raises(ValidationError, match="Incomplete projected unit"):
            summarize_projected_population_summaries([tank_a, invalid])


def test_population_rejects_one_organism_reused_across_declared_units() -> None:
    """Technical fragments cannot silently become independent unit replicates."""
    base = EcologyProjectedUnitSummary(
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
        metric="box_width",
        units=["mm"],
        organism_keys=["same-organism"],
        complete_organism_keys=["same-organism"],
        incomplete_organism_keys=[],
        parent_colony_keys=["parent-A"],
        sampling_windows_utc=["2026-04-03/2026-04-04"],
        unit_status="candidate",
        mean_absolute_change=1.0,
        mean_percent_change=10.0,
    )
    moved = base.model_copy(
        update={
            "experimental_unit_id": "tank-B",
            "sampling_windows_utc": ["2026-04-03/2026-04-05"],
        }
    )
    with pytest.raises(ValidationError, match="pooled across declared experimental units"):
        summarize_projected_population_summaries([base, moved])
    # A metric change must not hide an experimental-unit reassignment.
    # The organism is the same biological specimen for width and height.
    different_metric = moved.model_copy(update={"metric": "box_height"})
    with pytest.raises(ValidationError, match="pooled across declared experimental units"):
        summarize_projected_population_summaries([base, different_metric])
    with pytest.raises(ValidationError, match="pooled across declared experimental units"):
        summarize_projected_population_summaries([different_metric, base])

    # Distinct metrics remain valid when the organism stays in the same tank.
    same_unit_metric = different_metric.model_copy(update={"experimental_unit_id": "tank-A"})
    assert len(summarize_projected_population_summaries([base, same_unit_metric])) == 2

    # Re-labeling the unit *type* is also a reassignment, not an independent
    # replicate; do not silently pool the organism into a new design level.
    changed_design = different_metric.model_copy(
        update={"experimental_unit_type": "colony", "experimental_unit_id": "colony-A"}
    )
    with pytest.raises(ValidationError, match="pooled across declared experimental units"):
        summarize_projected_population_summaries([base, changed_design])


def test_projected_population_sd_is_stable_for_large_finite_unit_changes() -> None:
    """Large finite unit changes must not overflow from squaring deviations."""
    first = EcologyProjectedUnitSummary(
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
        metric="box_width",
        units=["mm"],
        organism_keys=["A"],
        complete_organism_keys=["A"],
        incomplete_organism_keys=[],
        parent_colony_keys=["colony-A"],
        sampling_windows_utc=["2026-04-03/2026-04-04"],
        unit_status="candidate",
        mean_absolute_change=1e155,
        mean_percent_change=10.0,
    )
    second = first.model_copy(
        update={
            "experimental_unit_id": "tank-B",
            "organism_keys": ["B"],
            "complete_organism_keys": ["B"],
            "parent_colony_keys": ["colony-B"],
            "mean_absolute_change": 2e155,
            "mean_percent_change": 30.0,
        }
    )
    summary = summarize_projected_population_summaries([second, first])[0]
    assert summary.declared_unit_count == 2
    assert summary.mean_unit_absolute_change == pytest.approx(1.5e155)
    assert summary.sample_sd_unit_absolute_change == pytest.approx(7.071067811865475e154)
    assert summary.sample_sd_unit_percent_change == pytest.approx(14.142135623730951)
    assert summary.independent_unit_inference_allowed is False
    assert summary.review_gate == "scientist_review_required"


def test_population_design_review_flags_missing_parent_without_inference() -> None:
    unit = EcologyProjectedUnitSummary(
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
        metric="box_width",
        units=["mm"],
        organism_keys=["A"],
        complete_organism_keys=["A"],
        incomplete_organism_keys=[],
        parent_colony_keys=[],
        sampling_windows_utc=["2026-04-03/2026-04-04"],
        unit_status="candidate",
        mean_absolute_change=2.0,
        mean_percent_change=20.0,
    )
    summary = summarize_projected_population_summaries([unit])[0]
    assert summary.units_missing_parent_colony == ["tank-A"]
    assert summary.design_review_blockers == [
        "independence_not_authenticated",
        "single_declared_unit",
        "missing_parent_colony",
    ]
    assert summary.independent_unit_inference_allowed is False
    assert summary.review_gate == "scientist_review_required"
