from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Job,
    PoseAnimalIdentity,
    PoseBiologicalEventRevision,
    PoseEventDetectionRun,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    PoseMeasurementRun,
    PoseMeasurementSeries,
)
from reefvision.jobs.pose_biological_measurement import (
    process_pose_biological_measurement_job,
)
from reefvision.services.pose_biological_measurement import PoseBiologicalMeasurementService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_identity_tracking_api import (
    SCHEMA_HASH,
    SCHEMA_ID,
    _first_class,
    _track,
    _video,
)


def test_service_exposes_measurement_event_review_and_export_contracts() -> None:
    names = {name for name in dir(PoseBiologicalMeasurementService) if not name.startswith("_")}
    assert {
        "submit_measurements",
        "execute_measurements",
        "submit_events",
        "execute_events",
        "correct_event",
        "export_json",
    } <= names


def test_fish_gape_vertical_slice_persists_reviews_and_export(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Phase 5 gape")
    video = _video(client, str(project["id"]), monkeypatch, "phase5-gape")
    track = _track(
        client,
        str(video["id"]),
        _first_class(project),
        offset=10,
        prefix="gape-source",
    )
    values = [1, 2, 7, 9, 8, 2, 1, 7, 10, 9, 2, 1]
    with client.app.state.session_factory() as session:
        run = PoseIdentityAssociationRun(
            project_id=str(project["id"]),
            video_id=str(video["id"]),
            pose_schema_id=SCHEMA_ID,
            pose_schema_revision=1,
            pose_schema_content_hash=SCHEMA_HASH,
            algorithm="synthetic-fixture",
            algorithm_version="1",
            parameters_json={},
            parameters_sha256="b" * 64,
            input_manifest_sha256="c" * 64,
            source_coordinate_space="source_pixels",
            source_width=320,
            source_height=180,
            status="completed",
            progress_json={"stage": "completed"},
            revision=1,
        )
        session.add(run)
        session.flush()
        identity = PoseAnimalIdentity(
            association_run_id=run.id,
            stable_identity_key="fish-1",
            display_name="Synthetic fish",
            origin="synthetic",
            verification_state="scientist_verified",
            lifecycle_state="active",
            first_frame=0,
            last_frame=len(values) - 1,
            revision=1,
        )
        session.add(identity)
        session.flush()
        for frame, gape in enumerate(values):
            session.add(
                PoseIdentityObservation(
                    observation_series_id=f"gape-{frame}",
                    revision=1,
                    association_run_id=run.id,
                    animal_identity_id=identity.id,
                    source_video_track_id=str(track["id"]),
                    source_detection_key=f"gape:{frame}",
                    frame_index=frame,
                    time_s=frame / 10,
                    bbox_json=[10, 10, 20, 20],
                    landmarks_json=[
                        {"landmark_id": "upper_jaw", "x": 10, "y": 10, "confidence": 0.95},
                        {
                            "landmark_id": "lower_jaw",
                            "x": 10,
                            "y": 10 + gape,
                            "confidence": 0.9,
                        },
                    ],
                    detection_confidence=0.95,
                    association_confidence=0.9,
                    visibility_state="visible",
                    assignment_source="synthetic_fixture",
                    verification_state="scientist_verified",
                    coordinate_space="source_pixels",
                    is_current=True,
                )
            )
        session.commit()
        identity_run_id = run.id

    submitted = client.post(
        f"/api/v1/projects/{project['id']}/pose-measurement-runs",
        json={
            "video_id": video["id"],
            "source_identity_run_id": identity_run_id,
            "source_identity_run_revision": 1,
            "verification_mode": "scientific",
            "definitions": [
                {
                    "id": "gape",
                    "name": "Gape distance",
                    "kind": "distance",
                    "landmark_ids": ["upper_jaw", "lower_jaw"],
                }
            ],
        },
    )
    assert submitted.status_code == 202, submitted.text
    measurement_job = submitted.json()
    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/pose-measurement-runs",
        json={
            "video_id": video["id"],
            "source_identity_run_id": identity_run_id,
            "source_identity_run_revision": 1,
            "verification_mode": "scientific",
            "definitions": [
                {
                    "id": "gape",
                    "name": "Gape distance",
                    "kind": "distance",
                    "landmark_ids": ["upper_jaw", "lower_jaw"],
                }
            ],
        },
    )
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["id"] == measurement_job["id"]
    measurement_run_id = cast(dict[str, str], measurement_job["result_json"])["run_id"]
    assert process_pose_biological_measurement_job(
        client.app.state.settings,
        client.app.state.session_factory,
        measurement_job["id"],
    )
    saved_measurements = client.get(
        f"/api/v1/projects/{project['id']}/pose-measurement-runs"
    )
    assert saved_measurements.status_code == 200, saved_measurements.text
    assert saved_measurements.json()[0]["source_job_id"] == measurement_job["id"]
    assert saved_measurements.json()[0]["definitions_json"][0]["id"] == "gape"
    series = client.get(f"/api/v1/pose-measurement-runs/{measurement_run_id}/series").json()
    assert len(series) == 1
    samples = client.get(f"/api/v1/pose-measurement-series/{series[0]['id']}/samples").json()
    assert [sample["pixel_value"] for sample in samples] == values

    detected = client.post(
        f"/api/v1/projects/{project['id']}/pose-event-runs",
        json={
            "measurement_run_id": measurement_run_id,
            "cycles": [
                {
                    "measurement_series_id": series[0]["id"],
                    "open_threshold": 6,
                    "close_threshold": 3,
                    "minimum_amplitude": 4,
                    "minimum_duration_s": 0.1,
                    "maximum_gap_s": 0.25,
                }
            ],
        },
    )
    assert detected.status_code == 202, detected.text
    event_job = detected.json()
    duplicate_event = client.post(
        f"/api/v1/projects/{project['id']}/pose-event-runs",
        json={
            "measurement_run_id": measurement_run_id,
            "cycles": [
                {
                    "measurement_series_id": series[0]["id"],
                    "open_threshold": 6,
                    "close_threshold": 3,
                    "minimum_amplitude": 4,
                    "minimum_duration_s": 0.1,
                    "maximum_gap_s": 0.25,
                }
            ],
        },
    )
    assert duplicate_event.status_code == 202, duplicate_event.text
    assert duplicate_event.json()["id"] == event_job["id"]
    event_run_id = cast(dict[str, str], event_job["result_json"])["run_id"]
    assert process_pose_biological_measurement_job(
        client.app.state.settings,
        client.app.state.session_factory,
        event_job["id"],
    )
    saved_event_runs = client.get(f"/api/v1/projects/{project['id']}/pose-event-runs")
    assert saved_event_runs.status_code == 200, saved_event_runs.text
    assert saved_event_runs.json()[0]["source_job_id"] == event_job["id"]
    assert saved_event_runs.json()[0]["configuration_json"]["cycles"][0][
        "measurement_series_id"
    ] == series[0]["id"]
    events = client.get(f"/api/v1/pose-event-runs/{event_run_id}/events").json()
    assert [
        (event["start_frame"], event["peak_frame"], event["end_frame"]) for event in events
    ] == [(2, 3, 5), (7, 8, 10)]
    current_events = list(events)
    adjusted = client.post(
        f"/api/v1/pose-biological-events/{events[0]['id']}/corrections",
        json={
            "action": "adjust_boundaries",
            "start_frame": 0,
            "end_frame": 5,
            "reason": "Include observed closed baseline",
            "actor": "tester",
        },
    )
    assert adjusted.status_code == 201, adjusted.text
    assert adjusted.json()["revision"] == 2
    assert adjusted.json()["amplitude"] == 8
    current_events[0] = adjusted.json()
    for event in current_events:
        confirmed = client.post(
            f"/api/v1/pose-biological-events/{event['id']}/corrections",
            json={
                "action": "confirm",
                "reason": "Synthetic engineering fixture",
                "actor": "tester",
            },
        )
        assert confirmed.status_code == 201, confirmed.text

    manual = client.post(
        f"/api/v1/pose-event-runs/{event_run_id}/events",
        json={
            "measurement_series_id": series[0]["id"],
            "start_frame": 6,
            "end_frame": 10,
            "cycle_state": "complete",
            "reason": "Synthetic manual-review exercise",
            "actor": "tester",
        },
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["detection_source"] == "scientist"
    history = client.get(
        f"/api/v1/pose-event-runs/{event_run_id}/events?include_history=true"
    ).json()
    assert len(history) == 6
    assert sum(event["is_current"] for event in history) == 3

    exported = client.get(f"/api/v1/pose-event-runs/{event_run_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["scientific_status"] == "scientist_reviewed"
    assert len(exported.json()["events"]) == 3
    assert len(exported.json()["event_history"]) == 6
    assert len(exported.json()["measurement_series"][0]["samples"]) == len(values)
    assert exported.json()["package_sha256"]
    exported_csv = client.get(f"/api/v1/pose-event-runs/{event_run_id}/export?format=csv")
    assert exported_csv.status_code == 200, exported_csv.text
    assert "measurement" in exported_csv.text
    assert "event_revision" in exported_csv.text

    cancelled = client.post(
        f"/api/v1/projects/{project['id']}/pose-measurement-runs",
        json={
            "video_id": video["id"],
            "source_identity_run_id": identity_run_id,
            "source_identity_run_revision": 1,
            "definitions": [
                {
                    "id": "cancelled-gape",
                    "name": "Cancelled gape",
                    "kind": "distance",
                    "landmark_ids": ["upper_jaw", "lower_jaw"],
                }
            ],
        },
    ).json()
    cancelled_run_id = cast(dict[str, str], cancelled["result_json"])["run_id"]
    with client.app.state.session_factory() as session:
        cancelled_job = session.get(Job, cancelled["id"])
        assert cancelled_job is not None
        cancelled_job.status = "cancel_requested"
        session.commit()
    assert process_pose_biological_measurement_job(
        client.app.state.settings, client.app.state.session_factory, cancelled["id"]
    )
    with client.app.state.session_factory() as session:
        cancelled_job = session.get(Job, cancelled["id"])
        cancelled_run = session.get(PoseMeasurementRun, cancelled_run_id)
        assert cancelled_job is not None and cancelled_job.status == "cancelled"
        assert cancelled_run is not None and cancelled_run.status == "cancelled"
        assert not list(
            session.scalars(
                select(PoseMeasurementSeries).where(
                    PoseMeasurementSeries.measurement_run_id == cancelled_run_id
                )
            )
        )

    failed = client.post(
        f"/api/v1/projects/{project['id']}/pose-event-runs",
        json={
            "measurement_run_id": measurement_run_id,
            "cycles": [
                {
                    "measurement_series_id": "missing-series",
                    "open_threshold": 6,
                    "close_threshold": 3,
                }
            ],
        },
    ).json()
    failed_run_id = cast(dict[str, str], failed["result_json"])["run_id"]
    assert process_pose_biological_measurement_job(
        client.app.state.settings, client.app.state.session_factory, failed["id"]
    )
    with client.app.state.session_factory() as session:
        failed_job = session.get(Job, failed["id"])
        failed_run = session.get(PoseEventDetectionRun, failed_run_id)
        assert failed_job is not None and failed_job.status == "failed"
        assert failed_run is not None and failed_run.status == "failed"
        assert not list(
            session.scalars(
                select(PoseBiologicalEventRevision).where(
                    PoseBiologicalEventRevision.event_detection_run_id == failed_run_id
                )
            )
        )
