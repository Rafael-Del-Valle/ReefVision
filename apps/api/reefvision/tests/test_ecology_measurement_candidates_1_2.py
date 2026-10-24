"""Standalone and saved Workflow Builder parity for projected ecological evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyProjectedUnitSummary,
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
    assert change.percent_change == 40.0
    assert change.elapsed_days == 1.0
    assert change.observed_timepoint_count == 2
    assert change.baseline_image_id == baseline.image_id
    assert change.final_image_id == "different-image"
    assert change.evidence_level == "linked_unverified"
    assert change.review_gate == "scientist_review_required"

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
            "annotation_evidence_id": "annotation-B-earlier",
            "value": 4.0,
        }
    )
    second_last = second_first.model_copy(
        update={
            "image_id": "B-later",
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
    assert summary.shared_parent_colony_keys == ["colony-1"]
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
