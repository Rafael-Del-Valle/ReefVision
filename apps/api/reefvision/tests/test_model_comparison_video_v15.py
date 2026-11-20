"""Exercise video comparison with synthetic observations scored by the real validation worker."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseAnimalIdentity,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    PoseTrainingDatasetItem,
    Project,
    VideoTrack,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.reefpose_validation import process_reefpose_validation_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_active_learning_phase8 import _build_temporal
from reefvision.tests.test_pose_identity_tracking_api import _video
from reefvision.tests.test_scientific_project_exchange import import_archive

VideoFixture = tuple[FastAPI, str, list[str], list[str], str]

VALUES = (1, 2, 7, 9, 8, 2, 1, 7, 10, 9, 2, 1)
BOX = [20, 20, 40, 30]
CONFIGURATION = {
    "definitions": [
        {"id": "gape", "name": "Gape", "kind": "distance", "landmark_ids": ["upper", "lower"]}
    ],
    "events": [
        {
            "label": "gape",
            "definition_id": "gape",
            "unit": "pixels",
            "open_threshold": 6,
            "close_threshold": 3,
        }
    ],
    "onset_tolerance_s": 0.2,
    "offset_tolerance_s": 0.2,
}


def _json(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.text
    return cast(dict[str, Any], response.json())


def _points(value: int, offset: int = 0) -> list[dict[str, Any]]:
    return [
        {"id": "upper", "x": 30 + offset, "y": 28, "visibility": "visible"},
        {"id": "lower", "x": 30 + offset, "y": 28 + value, "visibility": "visible"},
    ]


def _record(
    video: dict[str, object], schema: dict[str, Any], label: str, split: str
) -> dict[str, Any]:
    poses = [
        {"individual_id": label, "frame": frame, "bbox": BOX, "landmarks": _points(n)}
        for frame, n in enumerate(VALUES)
    ]
    events = [
        {"id": "cycle-a", "individual_id": label, "label": "gape", "start_s": 0.2, "end_s": 0.5},
        {"id": "cycle-b", "individual_id": label, "label": "gape", "start_s": 0.7, "end_s": 1.0},
    ]
    return {
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "group_id": label,
        "split": split,
        "schema_id": schema["id"],
        "schema_revision": 1,
        "schema_sha256": schema["content_hash"],
        "individuals": [{"id": label, "species": "Synthetic specimen"}],
        "exhaustive_identity_coverage": True,
        "exhaustive_event_coverage": True,
        "event_windows": [{"individual_id": label, "label": "gape", "start_s": 0.0, "end_s": 1.2}],
        "annotations": [
            {"rater_id": name, "blinded": True, "poses": poses, "events": events}
            for name in ("reference-a", "reference-b")
        ],
    }


def _freeze_training(
    client: TestClient,
    project: str,
    label_id: str,
    video: dict[str, object],
    schema: dict[str, Any],
) -> dict[str, Any]:
    track_body = {
        "label_class_id": label_id,
        "geometry_kind": "bbox",
        "keyframes": [
            {
                "frame": frame,
                "bbox": BOX,
                "confidence": 0.9,
                "pose_observations": [
                    {
                        "id": f"dev-{frame}-{point['id']}",
                        "landmark_id": point["id"],
                        "semantic_label": point["id"],
                        "occurrence_index": 0,
                        "x": point["x"],
                        "y": point["y"],
                        "confidence": 0.8,
                        "status": "visible",
                        "source": "model",
                    }
                    for point in _points(n)
                ],
            }
            for frame, n in enumerate(VALUES[:4])
        ],
        "interpolation": "hold",
        "status": "verified",
    }
    track = _json(client.post(f"/api/v1/videos/{video['id']}/tracks", json=track_body), 201)
    _json(
        client.put(
            f"/api/v1/video-tracks/{track['id']}",
            json={
                **track_body,
                "base_revision": track["revision"],
                "pose_schema_binding": {
                    "schema_id": schema["id"],
                    "schema_revision": 1,
                    "content_hash": schema["content_hash"],
                },
            },
        ),
        200,
    )
    _build_temporal(client, track["id"])
    round_ = _json(
        client.post(
            f"/api/v1/projects/{project}/pose-active-learning-rounds",
            json={
                "name": "Independent training recording",
                "video_id": video["id"],
                "track_ids": [track["id"]],
                "selection_unit": "frame",
                "requested_size": 1,
                "minimum_frame_spacing": 0,
                "grouping": {
                    "recording_id": "training-recording",
                    "animal_id": "development-animal",
                },
            },
        ),
        201,
    )
    candidates = client.get(f"/api/v1/pose-active-learning-rounds/{round_['id']}/candidates")
    assert candidates.status_code == 200, candidates.text
    (candidate,) = candidates.json()
    _json(
        client.put(
            f"/api/v1/pose-active-learning-candidates/{candidate['id']}/review",
            json={
                "action": "verify",
                "reviewed_by": "Synthetic source reviewer",
                "note": "Declared development fixture",
            },
        ),
        200,
    )
    return _json(
        client.post(
            f"/api/v1/pose-active-learning-rounds/{round_['id']}/training-dataset",
            json={
                "name": "Frozen development supervision",
                "created_by": "Synthetic source reviewer",
            },
        ),
        201,
    )


def _model(
    session: Session, settings: Settings, project: str, dataset: dict[str, Any], name: str
) -> str:
    project_row = session.get(Project, project)
    assert project_row is not None
    relative = f"{project_row.storage_root}/models/{name}.pt"
    file = settings.resolved_data_dir / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_id = f"structured-fixture-{name}".encode()
    file.write_bytes(checkpoint_id)
    model = ModelRegistration(
        project_id=project,
        purpose="detector",
        display_name=name,
        source_filename=f"{name}.pt",
        managed_path=relative,
        file_size_bytes=len(checkpoint_id),
        sha256=sha256(checkpoint_id).hexdigest(),
        framework="pytorch",
        task="pose",
        provider_name="reefpose",
        provider_version="fixture",
        metadata_json={
            "source_pose_training_dataset_id": dataset["id"],
            "source_pose_training_dataset_manifest_sha256": dataset["manifest_sha256"],
            "source_pose_validation_mode": "none",
        },
    )
    session.add(model)
    session.flush()
    return model.id


def _source(
    session: Session, reference: dict[str, Any], project: str, model: str, side: int, label_id: str
) -> str:
    parameters = {"max_gap": 3}
    run = PoseIdentityAssociationRun(
        project_id=project,
        video_id=reference["video_id"],
        source_model_id=model,
        status="completed",
        pose_schema_id=reference["schema_id"],
        pose_schema_revision=1,
        pose_schema_content_hash=reference["schema_sha256"],
        source_width=320,
        source_height=180,
        algorithm="structured-pose-fixture",
        algorithm_version="1",
        parameters_json=parameters,
        parameters_sha256=canonical_json_sha256(parameters),
        input_manifest_sha256="e" * 64,
    )
    session.add(run)
    session.flush()
    identity = PoseAnimalIdentity(
        association_run_id=run.id, stable_identity_key="fixture-fish", first_frame=0
    )
    session.add(identity)
    session.flush()
    track = VideoTrack(
        video_id=reference["video_id"],
        label_class_id=label_id,
        track_number=side + 1,
        source_model_id=model,
        status="machine_generated",
        interpolation="hold",
    )
    session.add(track)
    session.flush()
    for frame, value in enumerate(VALUES):
        if side and frame == 2:
            continue
        session.add(
            PoseIdentityObservation(
                observation_series_id=str(uuid4()),
                revision=1,
                association_run_id=run.id,
                animal_identity_id=identity.id,
                source_video_track_id=track.id,
                source_detection_key=f"fixture-{frame}",
                frame_index=frame,
                time_s=frame / 10.0,
                bbox_json=BOX,
                assignment_source="model",
                association_confidence=0.9,
                landmarks_json=[
                    {
                        "landmark_id": item["id"],
                        "x": item["x"],
                        "y": item["y"],
                        "visibility": "visible",
                        "confidence": 0.9,
                    }
                    for item in _points(value, offset=side * 2)
                ],
            )
        )
    return run.id


@pytest.fixture
def video_comparison(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> VideoFixture:
    app = cast(FastAPI, client.app)
    entry = create_project(client, "Paired scoring fixture")
    project = entry["id"]
    label_id = entry["label_classes"][0]["id"]
    scope = f"/api/v1/projects/{project}"
    recordings = [_video(client, project, monkeypatch, f"clip-{i}") for i in range(4)]
    schema = _json(
        client.post(
            scope + "/pose-schemas",
            json={
                "name": "Synthetic jaws",
                "landmarks": [{"id": "upper", "name": "Upper"}, {"id": "lower", "name": "Lower"}],
                "edges": [],
            },
        ),
        201,
    )
    reference_records = [
        _record(
            recordings[i],
            schema,
            f"heldout-{i}" if i else "protocol-development",
            "test" if i else "development",
        )
        for i in range(3)
    ]
    frozen = _json(
        client.post(
            scope + "/reefpose-references",
            json={
                "name": "Paired frozen fixture",
                "data_kind": "synthetic",
                "recordings": reference_records,
            },
        ),
        201,
    )
    dataset = _freeze_training(client, project, label_id, recordings[3], schema)
    jobs = []
    models = []
    for side in range(2):
        with app.state.session_factory() as session:
            model = _model(session, test_settings, project, dataset, f"Model-{side}")
            sources = {
                _record["video_id"]: _source(session, _record, project, model, side, label_id)
                for _record in reference_records
            }
            session.commit()
        inputs = {"reference_id": frozen["id"], "rater_id": "reference-a"}
        dev_id = reference_records[0]["video_id"]
        development = _json(
            client.post(
                scope + "/reefpose-validations",
                json={
                    **inputs,
                    "split": "development",
                    "configurations": [CONFIGURATION],
                    "source_runs": {dev_id: sources[dev_id]},
                },
            ),
            202,
        )
        assert process_reefpose_validation_job(
            test_settings, app.state.session_factory, development["id"]
        )
        scoring = _json(
            client.post(
                scope + "/reefpose-validations",
                json={
                    **inputs,
                    "split": "test",
                    "development_job_id": development["id"],
                    "source_runs": {
                        entry["video_id"]: sources[entry["video_id"]]
                        for entry in reference_records[1:]
                    },
                },
            ),
            202,
        )
        assert process_reefpose_validation_job(
            test_settings, app.state.session_factory, scoring["id"]
        )
        scored = _json(client.get(scope + f"/reefpose-validations/{scoring['id']}/export"), 200)
        assert scored["split"] == "test" and len(scored["recordings"]) == 2
        jobs.append(scoring["id"])
        models.append(model)
    return app, project, jobs, models, frozen["manifest_sha256"]


def _metrics(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in observation["metrics"]}


def test_compares_same_frozen_pose_tracking_and_event_jobs(video_comparison: VideoFixture) -> None:
    from reefvision.services.model_comparison_video_v15 import compare_video_models

    app, project, jobs, models, reference_sha256 = video_comparison
    with app.state.session_factory() as session:
        for task in ("pose", "tracking", "event"):
            report = compare_video_models(session, project, task, jobs, models)
            assert report == compare_video_models(session, project, task, jobs, models)
            assert report["reference_sha256"] == reference_sha256
            assert [row["group_id"] for row in report["groups"]] == ["heldout-1", "heldout-2"]
            assert len(report["source_sha256"]) == 2 and len(set(report["source_sha256"])) == 2
            for group in report["groups"]:
                assert all(row["media_kind"] == "video" for row in group["observations"])
                if task == "pose":
                    frame = next(row for row in group["observations"] if row.get("frame") == 0)
                    assert _metrics(frame)["joint_landmark_mean_error"]["left"] == 0.0
                    assert _metrics(frame)["joint_landmark_mean_error"]["right"] == 2.0
                    missing = next(row for row in group["observations"] if row.get("frame") == 2)
                    assert _metrics(missing)["visible_landmarks_missing"]["right"] == 2
                    assert _metrics(missing)["joint_landmark_mean_error"]["left"] is None
                elif task == "tracking":
                    missed = next(row for row in group["observations"] if row.get("frame") == 2)
                    assert _metrics(missed)["frame_identity_misses"]["right"] == 1
                else:
                    window = next(row for row in group["observations"] if row.get("seconds") == 0.0)
                    assert _metrics(window)["complete_reference_events"]["left"] == 2
                    assert "complete_event_misses" in _metrics(window)


def test_rejects_mismatched_selected_checkpoints_and_rehashed_settings(
    video_comparison: VideoFixture,
) -> None:
    from reefvision.services.model_comparison_video_v15 import compare_video_models

    app, project, job_ids, model_ids, _ = video_comparison
    with app.state.session_factory() as session:
        with pytest.raises(ValidationError, match="checkpoint"):
            compare_video_models(session, project, "pose", job_ids, model_ids[::-1])
        right = session.get(Job, job_ids[1])
        assert right is not None
        payload = deepcopy(right.result_json)
        payload["selected_configuration"]["iou_threshold"] = 0.91
        payload.pop("result_sha256")
        right.result_json = {**payload, "result_sha256": canonical_json_sha256(payload)}
        session.commit()
        with pytest.raises(ValidationError, match=r"protocol|config"):
            compare_video_models(session, project, "pose", job_ids, model_ids)


def test_rejects_same_animal_across_distinct_training_and_test_recordings(
    video_comparison: VideoFixture,
) -> None:
    from reefvision.services.model_comparison_video_v15 import compare_video_models

    app, project, job_ids, model_ids, _ = video_comparison
    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_ids[0])
        assert model is not None
        item = session.scalar(
            select(PoseTrainingDatasetItem).where(
                PoseTrainingDatasetItem.dataset_id
                == model.metadata_json["source_pose_training_dataset_id"]
            )
        )
        assert item is not None
        item.acquisition_provenance_json = {
            **item.acquisition_provenance_json,
            "source_grouping": {"recording_id": "distinct-recording", "animal_id": "HELDOUT-1"},
        }
        session.commit()
        with pytest.raises(ValidationError, match="overlaps"):
            compare_video_models(session, project, "tracking", job_ids, model_ids)


def test_rejects_changed_original_predictions_without_reclassifying_them_as_missing(
    video_comparison: VideoFixture,
) -> None:
    from reefvision.services.model_comparison_video_v15 import compare_video_models

    app, project, job_ids, model_ids, _ = video_comparison
    with app.state.session_factory() as session:
        job = session.get(Job, job_ids[1])
        assert job is not None and job.result_json is not None
        source = job.result_json["prediction_sources"][0]
        observation = session.scalar(
            select(PoseIdentityObservation)
            .where(PoseIdentityObservation.association_run_id == source["id"])
            .limit(1)
        )
        assert observation is not None
        observation.bbox_json = [21, 20, 40, 30]
        session.commit()
        with pytest.raises(ValidationError, match="no longer match"):
            compare_video_models(session, project, "event", job_ids, model_ids)


def test_compares_restored_exchange_reports(
    video_comparison: VideoFixture,
    client: TestClient,
    test_settings: Settings,
) -> None:
    from reefvision.services.model_comparison_video_v15 import compare_video_models

    app, project, job_ids, model_ids, _ = video_comparison
    with app.state.session_factory() as session:
        before = compare_video_models(session, project, "pose", job_ids, model_ids)
    export = _json(
        client.post(
            f"/api/v1/projects/{project}/exchange-packages",
            json={
                "include_media": True,
                "include_model_weights": True,
                "include_generated_artifacts": False,
            },
        ),
        202,
    )
    assert process_project_exchange_export_job(
        test_settings, app.state.session_factory, export["job_id"]
    )
    archive = client.get(f"/api/v1/exchange-packages/{export['package']['id']}/download")
    assert archive.status_code == 200, archive.text[:500]
    restored = _json(import_archive(client, archive.content), 201)
    id_map = restored["package"]["options_json"]["id_map"]
    with app.state.session_factory() as session:
        outcome = compare_video_models(
            session,
            restored["project_id"],
            "pose",
            [id_map[k] for k in job_ids],
            [id_map[k] for k in model_ids],
        )
    assert outcome["reference_id"] == id_map[before["reference_id"]]
    for group in before["groups"]:
        for observation in group["observations"]:
            observation["media_id"] = id_map[observation["media_id"]]
    assert outcome["groups"] == before["groups"]
