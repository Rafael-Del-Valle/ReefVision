from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.video_tracking as tracking_job_module
import reefvision.ml.provider_hub as provider_hub_module
import reefvision.ml.video_tracking as video_tracking_module
from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.jobs.video_tracking import _keyframes
from reefvision.ml.provider_adapters.ultralytics_multitask import (
    UltralyticsMultitaskProvider,
)
from reefvision.ml.sleap_nn_provider import (
    SLEAP_BUNDLE_FORMAT,
    SLEAP_BUNDLE_MANIFEST,
    SLEAP_NN_SUPPORTED_VERSION,
    SleapNNPoseRegistrationProvider,
    read_sleap_nn_bundle_manifest,
)
from reefvision.ml.video_tracking import (
    SleapNNVideoTrackingProvider,
    TrackObservation,
    VideoTrackingCancellationCheck,
    VideoTrackingProgress,
    VideoTrackingProgressCallback,
)
from reefvision.services import video_assets as video_assets_module
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


def test_sleap_bundle_registration_preserves_canonical_landmark_order(
    tmp_path: Path,
) -> None:
    bundle = _sleap_bundle(tmp_path)

    manifest = read_sleap_nn_bundle_manifest(bundle)
    metadata = SleapNNPoseRegistrationProvider().inspect_model(bundle)

    assert manifest.class_name == "jellyfish"
    assert manifest.model_paths == ("bottomup",)
    assert manifest.landmark_labels == (
        "bell_center",
        "tentacle",
        "tentacle",
    )
    assert metadata.task == "pose"
    assert metadata.provider_name == "sleap_nn"
    assert metadata.class_labels == ["jellyfish"]
    assert metadata.metadata["pose_keypoint_shape"] == [3, 3]
    assert metadata.metadata["pose_landmark_labels"] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]


def test_sleap_bundle_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    bundle = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../escape.txt", "unsafe")
        archive.writestr(
            SLEAP_BUNDLE_MANIFEST,
            json.dumps(
                {
                    "format": SLEAP_BUNDLE_FORMAT,
                    "provider_id": "sleap_nn",
                    "provider_version": SLEAP_NN_SUPPORTED_VERSION,
                    "class_name": "jellyfish",
                    "instance_mode": "single",
                    "model_paths": ["model"],
                    "landmark_labels": ["bell_center"],
                }
            ),
        )
        archive.writestr("model/training_config.yaml", "model: {}\n")
        archive.writestr("model/best.ckpt", b"checkpoint")

    with pytest.raises(ValidationError, match="unsafe archive path"):
        read_sleap_nn_bundle_manifest(bundle)


class _FakeArray:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows

    def tolist(self) -> list[list[float]]:
        return self.rows


class _FakeInstance:
    def __init__(
        self,
        rows: list[list[float]],
        *,
        track_name: str,
        score: float,
    ) -> None:
        self._rows = rows
        self.track = SimpleNamespace(name=track_name)
        self.score = score

    def numpy(self, *, scores: bool = False) -> _FakeArray:
        assert scores is True
        return _FakeArray(self._rows)


class _FakePredictor:
    calls: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def from_model_paths(
        cls,
        model_paths: list[str],
        **kwargs: Any,
    ) -> _FakePredictor:
        cls.calls.append(
            {
                "model_paths": model_paths,
                **kwargs,
            }
        )
        return cls()

    def predict(self, source: str) -> SimpleNamespace:
        assert source.endswith("source.mp4")
        return SimpleNamespace(
            labeled_frames=[
                SimpleNamespace(
                    frame_idx=0,
                    instances=[
                        _FakeInstance(
                            [
                                [10.0, 20.0, 0.9],
                                [math.nan, math.nan, 0.0],
                                [30.0, 40.0, 0.8],
                            ],
                            track_name="animal-a",
                            score=0.87,
                        )
                    ],
                ),
                SimpleNamespace(
                    frame_idx=1,
                    instances=[
                        _FakeInstance(
                            [
                                [11.0, 20.0, 0.91],
                                [15.0, 30.0, 0.7],
                                [31.0, 40.0, 0.82],
                            ],
                            track_name="animal-a",
                            score=0.88,
                        )
                    ],
                ),
            ]
        )


class _FakeTrackerConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def test_sleap_video_pose_normalizes_to_track_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _sleap_bundle(tmp_path)
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    _FakePredictor.calls.clear()
    monkeypatch.setattr(
        video_tracking_module,
        "sleap_predictor_types",
        lambda: (_FakePredictor, _FakeTrackerConfig),
    )

    provider = SleapNNVideoTrackingProvider()
    observations = provider.track(
        bundle,
        video,
        tracker="ignored-by-sleap",
        confidence=0.25,
        iou=0.5,
        device="cpu",
        link_detections=True,
    )

    assert provider.resolve_tracker_name(
        "bytetrack.yaml",
        link_detections=True,
    ) == "sleap_nn:fixed_window:oks:hungarian"
    assert len(observations) == 2
    assert {item.provider_track_id for item in observations} == {1}
    assert observations[0].class_name == "jellyfish"
    assert observations[0].keypoints == (
        (10.0, 20.0, 0.9),
        (0.0, 0.0, 0.0),
        (30.0, 40.0, 0.8),
    )
    assert observations[0].bbox == pytest.approx((9.0, 19.0, 22.0, 22.0))
    assert _FakePredictor.calls[0]["peak_threshold"] == 0.25
    assert isinstance(
        _FakePredictor.calls[0]["tracker_config"],
        _FakeTrackerConfig,
    )


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


def test_ultralytics_multitask_adapter_declares_pose_support() -> None:
    provider = UltralyticsMultitaskProvider()

    assert "pose" in provider.supported_tasks



def test_provider_catalog_exposes_optional_sleap_pose_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_hub_module,
        "sleap_nn_runtime_status",
        lambda: {
            "ready": False,
            "sleap_nn_version": None,
            "sleap_io_version": None,
            "issues": [
                "sleap-nn 0.3.3 is required (found missing)",
                "sleap-io 0.9.2 is required (found missing)",
            ],
        },
    )
    descriptor = provider_hub_module._sleap_nn_descriptor()

    assert descriptor.provider_id == "sleap_nn"
    assert descriptor.supported_tasks == ("pose",)
    assert descriptor.registerable is True
    assert descriptor.availability_status == "dependency_missing"
    assert descriptor.video_support is True
    assert descriptor.required_model_files == (".zip",)


def test_sleap_bundle_registers_without_optional_runtime(
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

    assert response.status_code == 200, response.text
    model = response.json()
    assert model["provider_name"] == "sleap_nn"
    assert model["task"] == "pose"
    assert model["framework"] == "sleap_nn"
    assert model["class_map_json"]["mapping"][class_name] == str(
        project["label_classes"][0]["id"]
    )
    assert model["metadata_json"]["pose_keypoint_shape"] == [3, 3]
    assert model["metadata_json"]["pose_landmark_labels"] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]

    bound = client.put(
        f"/api/v1/models/{model['id']}/pose-landmark-schema",
        json={
            "groups": [
                {"name": "bell_center", "count": 1},
                {"name": "tentacle", "count": 2},
            ]
        },
    )
    assert bound.status_code == 200, bound.text
    schema = bound.json()["metadata_json"]["pose_landmark_schema"]
    assert schema["expanded_labels"] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]


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
    machine = next(
        item
        for item in tracks
        if item["source_job_id"] == queued.json()["id"]
    )
    first_frame = machine["keyframes_json"][0]
    assert [item["semantic_label"] for item in first_frame["pose_observations"]] == [
        "bell_center",
        "tentacle",
        "tentacle",
    ]
    assert first_frame["pose_observations"][2]["status"] == "absent"
    assert first_frame["pose_observations"][2]["confidence"] == 0.0
    assert machine["metadata_json"]["pose_tracking"] is True

    temporal = client.get(
        f"/api/v1/video-tracks/{machine['id']}/pose-temporal"
    )
    assert temporal.status_code == 200, temporal.text
    summary = temporal.json()
    assert {
        observation["semantic_label"]
        for observation in summary["observations"]
    } == {"bell_center", "tentacle"}
    assert any(
        observation["visibility_state"] == "absent"
        for observation in summary["observations"]
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
