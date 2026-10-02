from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import reefvision.ml.video_tracking as video_tracking_module
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
)


def _sleap_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "jellyfish-pose.zip"
    manifest = {
        "format": SLEAP_BUNDLE_FORMAT,
        "provider_id": "sleap_nn",
        "provider_version": SLEAP_NN_SUPPORTED_VERSION,
        "class_name": "jellyfish",
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
    calls: list[dict[str, Any]] = []

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
