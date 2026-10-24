"""Standalone and saved Workflow Builder parity for projected ecological evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.schemas.ecology_measurement_candidates import EcologyMeasurementCandidate
from reefvision.services.ecology_measurement_candidates import summarize_sampling_date_qc
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _get(client: TestClient, project_id: str):
    return client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )


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
    assert all(
        row["qc_status"] == "missing_timestamps"
        for row in payload["sampling_date_qc"]
    )
    assert all(
        row["review_gate"] == "scientist_review_required"
        for row in payload["sampling_date_qc"]
    )

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(
        item for item in registry.json()
        if item["node_type"] == "ecology_identity_registry_source"
    )
    assert any(
        port["port_id"] == "measurement_candidates"
        and port["accepted_types"] == ["ecology_measurement_candidates"]
        for port in node["output_ports"]
    )
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        item for item in workflow["artifacts"]
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
        row["data_type"] == "ecology_measurement_candidates"
        for row in workflow["artifacts"]
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
        row for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
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
    assert summarize_sampling_date_qc([first, missing])[0].qc_status == "missing_timestamps"
    assert summarize_sampling_date_qc([first, missing])[0].missing_timestamp_image_ids == [
        "second-source-image"
    ]
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
    assert summarize_sampling_date_qc([first, local_time])[0].qc_status == (
        "date_series_candidate"
    )
