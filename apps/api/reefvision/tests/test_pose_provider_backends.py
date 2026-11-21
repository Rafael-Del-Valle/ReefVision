from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.video_tracking as tracking_job_module
import reefvision.ml.provider_hub as provider_hub_module
from reefvision.db.models import Job, ModelRegistration, WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.jobs.video_tracking import _keyframes
from reefvision.ml.provider_adapters.ultralytics_multitask import (
    UltralyticsMultitaskProvider,
)
from reefvision.ml.sleap_nn_provider import (
    SLEAP_BUNDLE_FORMAT,
    SLEAP_BUNDLE_MANIFEST,
    SLEAP_NN_SUPPORTED_VERSION,
)
from reefvision.ml.video_tracking import (
    TrackObservation,
    VideoTrackingCancellationCheck,
    VideoTrackingProgress,
    VideoTrackingProgressCallback,
)
from reefvision.services import video_assets as video_assets_module
from reefvision.services.workflow_pose import execute_pose_inference_adapter
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


def _sleap_bundle(
    tmp_path: Path,
    *,
    class_name: str = "jellyfish",
) -> Path:
    bundle = tmp_path / "jellyfish-pose.zip"
    manifest = {
        "format": SLEAP_BUNDLE_FORMAT,
        "provider_id": "sleap_nn",
        "provider_version": SLEAP_NN_SUPPORTED_VERSION,
        "class_name": class_name,
        "instance_mode": "multi",
        "model_paths": ["bottomup"],
        "landmark_labels": [
            "bell_center",
            "tentacle",
            "tentacle",
        ],
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            SLEAP_BUNDLE_MANIFEST,
            json.dumps(manifest),
        )
        archive.writestr("bottomup/training_config.yaml", "model: {}\n")
        archive.writestr("bottomup/best.ckpt", b"checkpoint")
    return bundle


def test_pose_keyframes_emit_repeated_labels_and_absent_landmarks() -> None:
    observation = TrackObservation(
        frame=4,
        provider_track_id=2,
        class_name="jellyfish",
        confidence=0.9,
        bbox=(1.0, 2.0, 30.0, 40.0),
        keypoints=(
            (5.0, 6.0, 0.95),
            (7.0, 8.0, 0.0),
            (9.0, 10.0, 0.75),
        ),
    )
    schema: dict[str, object] = {
        "expanded_labels": [
            "bell_center",
            "tentacle",
            "tentacle",
        ]
    }

    keyframe = _keyframes([observation], schema)[0]

    assert keyframe["keypoints"] == [
        [5.0, 6.0, 0.95],
        [7.0, 8.0, 0.0],
        [9.0, 10.0, 0.75],
    ]
    assert keyframe["pose_observations"] == [
        {
            "id": "provider:2:frame:4:landmark:0",
            "semantic_label": "bell_center",
            "occurrence_index": 0,
            "x": 5.0,
            "y": 6.0,
            "confidence": 0.95,
            "status": "visible",
            "source": "model",
        },
        {
            "id": "provider:2:frame:4:landmark:1",
            "semantic_label": "tentacle",
            "occurrence_index": 0,
            "x": 0.0,
            "y": 0.0,
            "confidence": 0.0,
            "status": "absent",
            "source": "model",
        },
        {
            "id": "provider:2:frame:4:landmark:2",
            "semantic_label": "tentacle",
            "occurrence_index": 1,
            "x": 9.0,
            "y": 10.0,
            "confidence": 0.75,
            "status": "visible",
            "source": "model",
        },
    ]


def test_pose_keyframes_emit_stable_ids_from_bound_custom_anatomy() -> None:
    observation = TrackObservation(
        frame=4,
        provider_track_id=2,
        class_name="jellyfish",
        confidence=0.9,
        bbox=(1.0, 2.0, 30.0, 40.0),
        keypoints=((5.0, 6.0, 0.95), (9.0, 10.0, 0.75)),
    )
    schema: dict[str, object] = {
        "expanded_labels": ["Tentacle", "Tentacle"],
        "landmarks": [
            {"id": "tentacle_right", "name": "Tentacle"},
            {"id": "tentacle_left", "name": "Tentacle"},
        ],
    }

    keyframe = _keyframes([observation], schema)[0]

    assert [item["landmark_id"] for item in keyframe["pose_observations"]] == [
        "tentacle_right",
        "tentacle_left",
    ]


def test_ultralytics_multitask_adapter_declares_pose_support() -> None:
    provider = UltralyticsMultitaskProvider()

    assert "pose" in provider.supported_tasks


def test_provider_catalog_preserves_retired_sleap_metadata() -> None:
    descriptor = provider_hub_module._sleap_nn_descriptor()

    assert descriptor.provider_id == "sleap_nn"
    assert descriptor.supported_tasks == ()
    assert descriptor.registerable is False
    assert descriptor.availability_status == "retired_license_audit"
    assert descriptor.video_support is False
    assert descriptor.required_model_files == ()


def test_provider_catalog_retirement_is_independent_of_installed_runtime() -> None:
    descriptor = provider_hub_module._sleap_nn_descriptor()

    assert descriptor.availability_status == "retired_license_audit"
    assert "authoritative SLEAP-NN license resolution" in str(descriptor.availability_reason)
    assert descriptor.required_packages[0].status == "retired_license_audit"
    assert descriptor.required_packages[1].status == "neutral_nwb_only"


def test_sleap_bundle_registration_is_retired_without_mutating_project(
    client: TestClient,
    tmp_path: Path,
) -> None:
    project = create_project(client, "SLEAP-NN registration")
    class_name = str(project["label_classes"][0]["name"])
    bundle = _sleap_bundle(tmp_path, class_name=class_name)

    with bundle.open("rb") as source:
        response = client.post(
            f"/api/v1/projects/{project['id']}/models/register",
            files={
                "file": (
                    "reefvision-sleap-pose.zip",
                    source.read(),
                    "application/zip",
                )
            },
            data={
                "purpose": "detector",
                "provider_name": "sleap_nn",
                "display_name": "Jellyfish SLEAP pose",
            },
        )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "retired pending an authoritative SLEAP-NN license resolution"
    )
    models = client.get(f"/api/v1/projects/{project['id']}/models")
    assert models.status_code == 200, models.text
    assert models.json() == []


def _fake_video_metadata(_path: Path) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 2,
        "fps": 10.0,
        "duration_seconds": 0.2,
    }


def _import_pose_video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(
        video_assets_module,
        "_inspect_video",
        _fake_video_metadata,
    )
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={
            "file": (
                "pose-source.mp4",
                io.BytesIO(b"fake-pose-video"),
                "video/mp4",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class _FakeCanonicalPoseVideoProvider:
    provider_id = "ultralytics"

    @property
    def provider_version(self) -> str:
        return "test-pose"

    def resolve_tracker_name(
        self,
        requested: str,
        *,
        link_detections: bool,
    ) -> str:
        return requested if link_detections else "instances-only"

    def track(
        self,
        checkpoint_path: Path,
        video_path: Path,
        *,
        tracker: str,
        confidence: float,
        iou: float,
        device: str,
        link_detections: bool = True,
        on_progress: VideoTrackingProgressCallback | None = None,
        should_cancel: VideoTrackingCancellationCheck | None = None,
    ) -> list[TrackObservation]:
        del tracker, confidence, iou, device, link_detections
        assert checkpoint_path.read_bytes() == b"pose-checkpoint"
        assert video_path.read_bytes() == b"fake-pose-video"
        observations = [
            TrackObservation(
                frame=0,
                provider_track_id=5,
                class_name="jellyfish",
                confidence=0.9,
                bbox=(10.0, 10.0, 40.0, 30.0),
                keypoints=(
                    (20.0, 20.0, 0.95),
                    (25.0, 30.0, 0.8),
                    (0.0, 0.0, 0.0),
                ),
            ),
            TrackObservation(
                frame=1,
                provider_track_id=5,
                class_name="jellyfish",
                confidence=0.91,
                bbox=(11.0, 10.0, 40.0, 30.0),
                keypoints=(
                    (21.0, 20.0, 0.96),
                    (26.0, 30.0, 0.82),
                    (31.0, 35.0, 0.7),
                ),
            ),
        ]
        if on_progress is not None:
            on_progress(
                VideoTrackingProgress(
                    frames_processed=2,
                    detections_seen=2,
                    tracked_observations_seen=2,
                    unique_tracks_seen=1,
                )
            )
        return observations


def _pose_model(
    client: TestClient,
    project: dict[str, object],
    app: FastAPI,
    *,
    with_schema: bool,
) -> str:
    model_id = "d2e9f1d2-f5e8-46d0-b859-90cb2ec1944e"
    label_class_id = str(project["label_classes"][0]["id"])
    managed_relative = f"{project['storage_root']}/models/{model_id}.pt"
    managed_path = resolve_managed_project_path(
        app.state.settings,
        managed_relative,
    )
    managed_path.parent.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(b"pose-checkpoint")
    with app.state.session_factory() as session:
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=str(project["id"]),
                purpose="detector",
                display_name="Canonical pose",
                source_filename="pose.pt",
                managed_path=managed_relative,
                sha256="d" * 64,
                file_size_bytes=len(b"pose-checkpoint"),
                framework="ultralytics",
                task="pose",
                provider_name="ultralytics",
                provider_version="test",
                class_map_json={
                    "labels": ["jellyfish"],
                    "mapping": {"jellyfish": label_class_id},
                },
                input_size_json={"width": 640, "height": 640},
                metadata_json={"pose_keypoint_shape": [3, 3]},
            )
        )
        session.commit()

    if with_schema:
        bound = client.put(
            f"/api/v1/models/{model_id}/pose-landmark-schema",
            json={
                "groups": [
                    {"name": "bell_center", "count": 1},
                    {"name": "tentacle", "count": 2},
                ]
            },
        )
        assert bound.status_code == 200, bound.text
    return model_id


@pytest.mark.parametrize("standalone", [False, True])
def test_retired_pose_video_never_creates_tracking_work(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, standalone: bool
) -> None:
    project = create_project(client, "Preserved video pose history")
    project_id = str(project["id"])
    video = _import_pose_video(client, project_id, monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _pose_model(client, project, app, with_schema=True)
    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        model.provider_name = "sleap_nn"
        model.provider_version = "0.3.3"
        model.framework = "sleap_nn"
        session.commit()

    model_path = f"/api/v1/models/{model_id}"
    historical_model = client.get(model_path).json()
    if standalone:
        result = client.post(
            f"/api/v1/videos/{video['id']}/tracking-jobs",
            json={"model_id": model_id, "tracking_mode": "auto", "device": "cpu"},
        )
        assert result.status_code == 400, (result.status_code, result.json().get("status"))
        assert "retired" in result.json()["detail"]
    else:
        with (
            app.state.session_factory() as session,
            pytest.raises(ValidationError, match="retired"),
        ):
            execute_pose_inference_adapter(
                session,
                app.state.settings,
                project_id,
                {"device": "cpu"},
                {
                    "video": [WorkflowArtifact(payload_json={"video_id": video["id"]})],
                    "model": [WorkflowArtifact(payload_json={"model_id": model_id})],
                },
            )
    with app.state.session_factory() as session:
        assert session.scalar(select(Job).where(Job.job_type == "video_tracking")) is None
    assert client.get(model_path).json() == historical_model


def test_pose_video_job_fails_closed_without_canonical_landmark_schema(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Pose schema required")
    video = _import_pose_video(client, str(project["id"]), monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _pose_model(
        client,
        project,
        app,
        with_schema=False,
    )

    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "tracker": "bytetrack.yaml",
            "device": "cpu",
            "minimum_track_frames": 1,
        },
    )
    assert queued.status_code == 200, queued.text

    assert (
        tracking_job_module.process_video_tracking_job(
            app.state.settings,
            app.state.session_factory,
            queued.json()["id"],
        )
        is False
    )
    job = client.get(f"/api/v1/jobs/{queued.json()['id']}").json()
    assert job["status"] == "failed"
    assert "requires a bound ReefVision landmark schema" in job["error_message"]


def test_pose_video_job_persists_provider_neutral_canonical_landmarks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Canonical pose provider handoff")
    first_class = project["label_classes"][0]
    first_class["name"] = "jellyfish"
    video = _import_pose_video(client, str(project["id"]), monkeypatch)
    app = cast(FastAPI, client.app)
    model_id = _pose_model(
        client,
        project,
        app,
        with_schema=True,
    )
    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        model.class_map_json = {
            "labels": ["jellyfish"],
            "mapping": {
                "jellyfish": str(project["label_classes"][0]["id"]),
            },
        }
        session.commit()

    monkeypatch.setattr(
        tracking_job_module,
        "video_tracking_provider_for_name",
        lambda _name: _FakeCanonicalPoseVideoProvider(),
    )
    queued = client.post(
        f"/api/v1/videos/{video['id']}/tracking-jobs",
        json={
            "model_id": model_id,
            "tracker": "bytetrack.yaml",
            "confidence": 0.25,
            "iou": 0.5,
            "device": "cpu",
            "minimum_track_frames": 1,
        },
    )
    assert queued.status_code == 200, queued.text

    assert tracking_job_module.process_video_tracking_job(
        app.state.settings,
        app.state.session_factory,
        queued.json()["id"],
    )
    tracks = client.get(f"/api/v1/videos/{video['id']}/tracks").json()
    machine = next(item for item in tracks if item["source_job_id"] == queued.json()["id"])
    first_frame = machine["keyframes_json"][0]
    assert [item["semantic_label"] for item in first_frame["pose_observations"]] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]
    assert first_frame["pose_observations"][2]["status"] == "absent"
    assert first_frame["pose_observations"][2]["confidence"] == 0.0
    assert machine["metadata_json"]["pose_tracking"] is True

    temporal = client.get(f"/api/v1/video-tracks/{machine['id']}/pose-temporal")
    assert temporal.status_code == 200, temporal.text
    summary = temporal.json()
    assert {observation["semantic_label"] for observation in summary["observations"]} == {
        "bell_center",
        "tentacle",
    }
    assert any(
        observation["visibility_state"] == "absent" for observation in summary["observations"]
    )


def test_pose_keyframe_mapping_rejects_schema_count_mismatch() -> None:
    observation = TrackObservation(
        frame=0,
        provider_track_id=1,
        class_name="jellyfish",
        confidence=0.9,
        bbox=(0.0, 0.0, 20.0, 20.0),
        keypoints=((5.0, 5.0, 0.9), (10.0, 10.0, 0.8)),
    )

    with pytest.raises(
        ValidationError,
        match="landmark count does not match",
    ):
        _keyframes(
            [observation],
            {"expanded_labels": ["bell_center"]},
        )
