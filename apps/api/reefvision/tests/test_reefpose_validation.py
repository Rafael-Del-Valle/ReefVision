from __future__ import annotations

from copy import deepcopy

import pytest
from alembic import command
from fastapi.testclient import TestClient

from reefvision.config import clear_settings_cache
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
)
from reefvision.repositories.jobs import JobRepository
from reefvision.schemas.reefpose_validation import ReferenceRecording, ValidationConfiguration
from reefvision.services.reefpose_validation_analysis import analyze
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_biological_measurement_migration import _config
from reefvision.tests.test_pose_identity_tracking_api import _first_class, _track, _video


def freeze_fixture(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    project = create_project(client, "Independent reference fixture")
    project_id = str(project["id"])
    video = _video(client, project_id, monkeypatch, "phase6-reference")
    schema = client.post(
        f"/api/v1/projects/{project_id}/pose-schemas",
        json={"name": "Fish jaws", "landmarks": [{"id": "jaw", "name": "Jaw"}], "edges": []},
    )
    assert schema.status_code == 201, schema.text
    recording = {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "group_id": "session-a",
        "exhaustive_identity_coverage": True,
        "split": "development",
        "individuals": [{"id": "animal-a", "species": "synthetic fish"}],
        "schema_id": schema.json()["id"],
        "schema_revision": 1,
        "schema_sha256": schema.json()["content_hash"],
        "event_windows": [
            {"individual_id": "animal-a", "label": "gape", "start_s": 0, "end_s": 0.5}
        ],
        "annotations": [
            {
                "rater_id": rater,
                "blinded": True,
                "events": [
                    {
                        "id": "cycle-1",
                        "individual_id": "animal-a",
                        "label": "gape",
                        "start_s": 0.1,
                        "end_s": end,
                    }
                ],
            }
            for rater, end in (("rater-a", 0.3), ("rater-b", 0.4))
        ],
    }
    payload = {"name": "Synthetic study", "data_kind": "synthetic", "recordings": [recording]}
    url = f"/api/v1/projects/{project_id}/reefpose-references"
    response = client.post(url, json=payload)
    assert response.status_code == 201, response.text
    return url, payload, response.json()


def test_reference_freezes_independent_annotations_and_appends_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, first = freeze_fixture(client, monkeypatch)
    payload["parent_id"] = first["id"]
    payload["recordings"][0]["annotations"][1]["events"][0]["end_s"] = 0.45
    second = client.post(url, json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["revision"] == 2
    assert second.json()["manifest_sha256"] != first["manifest_sha256"]
    original = client.get(f"{url}/{first['id']}").json()
    assert original["manifest"]["recordings"][0]["annotations"][1]["events"][0]["end_s"] == 0.4
    assert len(original["manifest"]["recordings"][0]["annotation_sha256"]) == 2


def test_reference_rejects_shared_recording_group_across_splits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, _ = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    other_video = _video(client, project_id, monkeypatch, "phase6-test")
    payload["recordings"].append(
        {
            **payload["recordings"][0],
            "split": "test",
            "video_id": other_video["id"],
            "video_sha256": other_video["sha256"],
        }
    )
    response = client.post(url, json=payload)
    assert response.status_code in (400, 422)
    assert "group" in response.text.lower()


def test_reference_cannot_relabel_a_test_video_for_development(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, payload, _ = freeze_fixture(client, monkeypatch)
    payload["data_kind"] = "biological"
    payload["recordings"][0]["split"] = "test"
    response = client.post(url, json=payload)
    assert response.status_code == 400
    assert "another split" in response.text


def test_reference_rejects_invalid_physical_calibration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, payload, _ = freeze_fixture(client, monkeypatch)
    payload["recordings"][0]["calibration"] = {
        "pixels_per_unit": 0,
        "unit": "mm",
        "source": "synthetic calibration",
    }
    response = client.post(url, json=payload)
    assert response.status_code == 422
    assert "pixels_per_unit" in response.text


def test_validation_distinguishes_identity_switches_from_missing_landmarks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, payload, _ = freeze_fixture(client, monkeypatch)
    recording = payload["recordings"][0]
    subjects = [("animal-a", 10), ("animal-b", 100)]
    recording["individuals"].append({"id": "animal-b", "species": "synthetic fish"})
    poses = []
    observations = []
    for frame in range(3):
        for index, (individual, x) in enumerate(subjects):
            bbox = [x, 10, 30, 30]
            poses.append(
                {
                    "individual_id": individual,
                    "frame": frame,
                    "bbox": bbox,
                    "landmarks": [{"id": "jaw", "x": x, "y": 15, "visibility": "visible"}],
                    "crossing": frame == 2,
                }
            )
            observations.append(
                {
                    "id": f"det-{frame}-{index}",
                    "identity_id": f"pred-{index if frame < 2 else 1 - index}",
                    "frame": frame,
                    "time_s": frame / 10,
                    "bbox": bbox,
                    "landmarks": (
                        []
                        if (frame, index) == (2, 1)
                        else [
                            {
                                "landmark_id": "jaw",
                                "x": x,
                                "y": 15,
                                "confidence": 0.9,
                                "visibility": "visible",
                            }
                        ]
                    ),
                    "association_confidence": 0.9,
                }
            )
    for annotation in recording["annotations"]:
        annotation["poses"] = poses
    reference = ReferenceRecording.model_validate(recording)
    report = analyze(
        [
            (
                reference,
                reference.annotations[0],
                {"fps": 10, "observations": observations},
                {"jaw": "Jaw"},
            )
        ],
        [ValidationConfiguration()],
        7,
        lambda: None,
    )
    assert report["identity"]["id_f1"] == pytest.approx(2 / 3)
    assert report["identity"]["identity_switches"] == 2
    identity = report["recordings"][0]["identity"]
    assert identity["crossing_total"] == 2
    assert identity["crossing_identity_matches"] == 0
    assert {row["frame"] for row in identity["switches"]} == {2}
    assert report["pose"]["matched_visible_count"] == 5


def test_validation_dispatcher_leaves_workflow_child_for_its_parent(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
        child = Job(
            job_type="reefpose_validation",
            status="queued",
            request_json={"workflow_run_id": "parent", "workflow_node_run_id": "score"},
        )
        direct = Job(job_type="reefpose_validation", status="queued", request_json={})
        session.add(child)
        session.flush()
        session.add(direct)
        session.commit()
        child_id = child.id
        assert JobRepository(session).next_queued() is direct
        direct.status = "succeeded"
        session.commit()
        assert JobRepository(session).next_queued() is None
        child.status = "failed"
        session.commit()
    retry = client.post(f"/api/v1/jobs/{child_id}/retry")
    assert retry.status_code == 409
    assert "parent workflow" in retry.text


def test_complete_zero_detection_job_can_be_scored(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, payload, frozen = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    recording = payload["recordings"][0]
    with client.app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project_id,
            display_name="Synthetic detector",
            provider_name="reefpose",
            task="pose",
            managed_path="fixture.pt",
            sha256="a" * 64,
            purpose="detector",
            source_filename="fixture.pt",
            file_size_bytes=1,
            framework="pytorch",
            provider_version="fixture",
        )
        session.add(model)
        session.flush()
        tracking = Job(
            project_id=project_id,
            job_type="video_tracking",
            status="succeeded",
            result_json={
                "video_id": recording["video_id"],
                "model_id": model.id,
                "pose_landmark_schema": {
                    "schema_id": recording["schema_id"],
                    "schema_revision": 1,
                    "content_hash": recording["schema_sha256"],
                },
                "detection_count": 0,
                "pose_track_hashes": {},
                "pose_input_hashes": {
                    "model_sha256": model.sha256,
                    "video_sha256": recording["video_sha256"],
                },
            },
        )
        session.add(tracking)
        session.commit()
        tracking_id = tracking.id
    jobs = f"/api/v1/projects/{project_id}/reefpose-validations"
    response = client.post(
        jobs,
        json={
            "reference_id": frozen["id"],
            "source_runs": {},
            "zero_detection_jobs": {recording["video_id"]: tracking_id},
            "rater_id": "rater-a",
            "configurations": [
                {
                    "definitions": [
                        {
                            "id": "gap",
                            "name": "Displacement",
                            "kind": "displacement",
                            "landmark_ids": ["jaw"],
                        }
                    ],
                    "events": [
                        {
                            "label": "gape",
                            "definition_id": "gap",
                            "unit": "pixels",
                            "open_threshold": 5,
                            "close_threshold": 2,
                        }
                    ],
                }
            ],
        },
    )
    assert response.status_code == 202, response.text
    from reefvision.jobs.reefpose_validation import process_reefpose_validation_job

    job_id = response.json()["id"]
    assert process_reefpose_validation_job(
        client.app.state.settings,
        client.app.state.session_factory,
        job_id,
    )
    assert client.get(f"{jobs}/{job_id}/export").json()["sensitivity"][0]["complete"]["fn"] == 1


def test_reference_migration_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    path = tmp_path / "reference.db"
    monkeypatch.setenv("REEFVISION_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = _config(path)
    clear_settings_cache()
    try:
        command.upgrade(config, "reefpose_0044")
        command.downgrade(config, "reefpose_0042")
        with sqlite3.connect(path) as database:
            tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master")}
            assert "reefpose_references" not in tables
            assert "reefpose_heldout_locks" not in tables
            assert "pose_measurement_runs" in tables
        command.upgrade(config, "reefpose_0044")
        with sqlite3.connect(path) as database:
            assert database.execute("SELECT count(*) FROM reefpose_references").fetchone() == (0,)
            assert database.execute("SELECT count(*) FROM reefpose_heldout_locks").fetchone() == (
                0,
            )
    finally:
        clear_settings_cache()


def test_validation_persists_original_machine_comparison_and_development_sensitivity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, payload, _ = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    recording = payload["recordings"][0]
    track = _track(
        client,
        recording["video_id"],
        _first_class(client.get(f"/api/v1/projects/{project_id}").json()),
        offset=0,
        prefix="validation",
    )
    for annotation in recording["annotations"]:
        annotation["measurements"] = [
            {
                "individual_id": "animal-a",
                "definition_id": "gape",
                "frame": frame,
                "unit": "pixels",
                "value": expected,
            }
            for frame, expected in ((1, 1), (2, 3), (3, 1))
        ]
        annotation["events"][0].update(amplitude=5, amplitude_unit="pixels")
        annotation["poses"] = [
            {
                "individual_id": "animal-a",
                "frame": frame,
                "bbox": [10, 10, 30, 30],
                "landmarks": [{"id": "jaw", "visibility": "visible", "x": 10 + frame, "y": 15}],
            }
            for frame in range(5)
        ]
    heldout_video = _video(client, project_id, monkeypatch, "phase6-heldout")
    heldout = deepcopy(recording)
    heldout.update(
        video_id=heldout_video["id"],
        video_sha256=heldout_video["sha256"],
        group_id="session-b",
        split="test",
    )
    payload["recordings"].append(heldout)
    frozen = client.post(url, json=payload)
    assert frozen.status_code == 201, frozen.text
    with client.app.state.session_factory() as session:
        run = PoseIdentityAssociationRun(
            project_id=project_id,
            video_id=recording["video_id"],
            status="completed",
            pose_schema_id=recording["schema_id"],
            pose_schema_revision=1,
            pose_schema_content_hash=recording["schema_sha256"],
            algorithm="synthetic",
            algorithm_version="1",
            parameters_json={},
            parameters_sha256="a" * 64,
            input_manifest_sha256="b" * 64,
            source_width=320,
            source_height=180,
        )
        session.add(run)
        session.flush()
        from reefvision.db.models import PoseAnimalIdentity

        identity = PoseAnimalIdentity(
            association_run_id=run.id,
            stable_identity_key="pred-a",
            first_frame=0,
        )
        session.add(identity)
        session.flush()
        for frame, x in enumerate((10, 11, 18, 19, 20)):
            session.add(
                PoseIdentityObservation(
                    observation_series_id=f"synthetic-{frame}",
                    revision=1,
                    association_run_id=run.id,
                    animal_identity_id=identity.id,
                    source_video_track_id=track["id"],
                    source_detection_key=f"det-{frame}",
                    frame_index=frame,
                    time_s=frame / 10,
                    bbox_json=[10, 10, 30, 30],
                    landmarks_json=[
                        {
                            "landmark_id": "jaw",
                            "x": x,
                            "y": 15,
                            "visibility": "visible",
                            "confidence": 0.9,
                        }
                    ],
                    association_confidence=0.9,
                    assignment_source="model",
                )
            )
        session.commit()
        run_id = run.id
    validation_url = f"/api/v1/projects/{project_id}/reefpose-validations"
    body = {
        "reference_id": frozen.json()["id"],
        "split": "development",
        "source_runs": {recording["video_id"]: run_id},
        "rater_id": "rater-a",
        "configurations": [
            {
                "definitions": [
                    {
                        "id": "gape",
                        "name": "Jaw movement",
                        "kind": "displacement",
                        "landmark_ids": ["jaw"],
                    }
                ],
                "events": [
                    {
                        "label": "gape",
                        "definition_id": "gape",
                        "unit": "pixels",
                        "open_threshold": 5,
                        "close_threshold": 2,
                    }
                ],
            },
            {
                "definitions": [
                    {
                        "id": "gape",
                        "name": "Jaw movement",
                        "kind": "displacement",
                        "landmark_ids": ["jaw"],
                    }
                ],
                "events": [
                    {
                        "label": "gape",
                        "definition_id": "gape",
                        "unit": "pixels",
                        "open_threshold": 10,
                        "close_threshold": 2,
                    }
                ],
            },
        ],
    }
    response = client.post(validation_url, json=body)
    assert response.status_code == 202, response.text
    from reefvision.jobs.reefpose_validation import process_reefpose_validation_job

    job_id = response.json()["id"]
    cancelled = client.post(validation_url, json=body)
    assert cancelled.status_code == 202, cancelled.text
    cancelled_id = cancelled.json()["id"]
    cancel = client.post(f"/api/v1/jobs/{cancelled_id}/cancel")
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"
    assert not process_reefpose_validation_job(
        client.app.state.settings, client.app.state.session_factory, cancelled_id
    )
    assert client.get(f"{validation_url}/{cancelled_id}/export").status_code == 400
    assert process_reefpose_validation_job(
        client.app.state.settings, client.app.state.session_factory, job_id
    )
    report = client.get(f"{validation_url}/{job_id}/export")
    assert report.status_code == 200, report.text
    result = report.json()
    assert result["identity"]["id_f1"] == 1
    assert result["pose"]["matched_visible_count"] == 5
    assert [(row["complete"]["tp"], row["complete"]["fn"]) for row in result["sensitivity"]] == [
        (1, 0),
        (0, 1),
    ]
    assert result["selected_configuration_index"] == 0
    assert result["data_kind"] == "synthetic"
    assert result["result_sha256"]
    assert "onset_error_s" in client.get(f"{validation_url}/{job_id}/export?format=csv").text
    assert result["inter_observer"]["events"][0]["f1"] == 1
    assert result["inter_observer"]["events"][0]["matches"][0]["offset_error_s"] == pytest.approx(
        0.1
    )
    assert result["recordings"][0]["measurements"][0]["bias"] == pytest.approx(4 / 3)
    assert result["recordings"][0]["events"][0]["complete"]["matches"][0]["amplitude_error"] == 1

    replay = client.post(validation_url, json=body)
    assert replay.status_code == 202, replay.text
    replay_id = replay.json()["id"]
    assert process_reefpose_validation_job(
        client.app.state.settings, client.app.state.session_factory, replay_id
    )
    assert (
        client.get(f"{validation_url}/{replay_id}/export").json()["result_sha256"]
        == result["result_sha256"]
    )
    rejected = client.post(
        validation_url,
        json={
            **body,
            "split": "test",
            "development_job_id": job_id,
        },
    )
    assert rejected.status_code == 422

    with client.app.state.session_factory() as session:
        # An empty but completed machine output is a valid held-out miss.
        test_run = PoseIdentityAssociationRun(
            project_id=project_id,
            video_id=heldout["video_id"],
            status="completed",
            pose_schema_id=heldout["schema_id"],
            pose_schema_revision=1,
            pose_schema_content_hash=heldout["schema_sha256"],
            algorithm="synthetic",
            algorithm_version="1",
            parameters_json={},
            parameters_sha256="a" * 64,
            input_manifest_sha256="c" * 64,
            source_width=320,
            source_height=180,
        )
        session.add(test_run)
        session.commit()
        heldout_run_id = test_run.id
    heldout_response = client.post(
        validation_url,
        json={
            "reference_id": frozen.json()["id"],
            "split": "test",
            "rater_id": "rater-b",
            "source_runs": {heldout["video_id"]: heldout_run_id},
            "development_job_id": job_id,
        },
    )
    assert heldout_response.status_code == 202, heldout_response.text
    heldout_job = heldout_response.json()["id"]
    assert process_reefpose_validation_job(
        client.app.state.settings, client.app.state.session_factory, heldout_job
    )
    test_report = client.get(f"{validation_url}/{heldout_job}/export").json()
    assert test_report["development_lock_sha256"] == result["result_sha256"]
    assert test_report["configurations"] == [result["selected_configuration"]]
    assert test_report["sensitivity"][0]["complete"]["fn"] == 1
    assert test_report["pose"]["matched_visible_count"] == 0
    assert test_report["identity"]["id_false_negatives"] == 5
    assert test_report["recordings"][0]["measurements"][0]["n"] == 0
    changed_protocol = client.post(
        validation_url,
        json={
            "reference_id": frozen.json()["id"],
            "split": "test",
            "rater_id": "rater-a",
            "source_runs": {heldout["video_id"]: heldout_run_id},
            "development_job_id": job_id,
        },
    )
    assert changed_protocol.status_code == 409
    assert "already locked" in changed_protocol.text
    summary = client.get(f"{validation_url}/{heldout_job}/export?format=summary")
    assert summary.status_code == 200
    assert "report_sha256,video_id,individual" in summary.text

    from reefvision.db.models import WorkflowArtifact
    from reefvision.services.workflow_reefpose_validation import (
        reference_adapter,
        validation_adapter,
    )

    with client.app.state.session_factory() as session:
        settings = client.app.state.settings
        reference = reference_adapter(
            session,
            settings,
            project_id,
            {"reference_id": frozen.json()["id"]},
            {},
        )[0]["payload"]
        artifacts = {
            "reference": [WorkflowArtifact(payload_json=reference)],
            "tracks": [
                WorkflowArtifact(
                    payload_json={
                        "run_id": run_id,
                        "video_id": recording["video_id"],
                        "input_manifest_sha256": "b" * 64,
                    }
                )
            ],
        }
        workflow_params = {
            key: value for key, value in body.items() if key not in {"reference_id", "source_runs"}
        }
        workflow_params.update(
            __workflow_run_id="synthetic-workflow", __workflow_node_run_id="score"
        )
        output = validation_adapter(
            session,
            settings,
            project_id,
            workflow_params,
            artifacts,
        )
        assert output[0]["data_type"] == "reefpose_validation_report"
        assert output[0]["payload"]["result_sha256"] == result["result_sha256"]
        assert (
            validation_adapter(session, settings, project_id, workflow_params, artifacts) == output
        )
