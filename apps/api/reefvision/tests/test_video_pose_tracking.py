from __future__ import annotations

from reefvision.jobs.video_tracking import _keyframes
from reefvision.ml.video_tracking import TrackObservation
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.services.video_tracks import _keyframe_payload


def test_pose_keypoints_are_persisted_in_machine_track_keyframes() -> None:
    observation = TrackObservation(
        frame=12,
        provider_track_id=7,
        class_name="dolphin",
        confidence=0.91,
        bbox=(10.0, 20.0, 30.0, 40.0),
        keypoints=(
            (12.5, 24.5, 0.95),
            (20.0, 30.0, 0.72),
            (0.0, 0.0, 0.0),
        ),
    )

    keyframe = _keyframes([observation])[0]

    assert keyframe["frame"] == 12
    assert keyframe["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert keyframe["keypoints"] == [
        [12.5, 24.5, 0.95],
        [20.0, 30.0, 0.72],
        [0.0, 0.0, 0.0],
    ]


def test_pose_keypoints_survive_track_edit_schema_validation() -> None:
    keyframe = VideoTrackKeyframe.model_validate(
        {
            "frame": 3,
            "bbox": [1.0, 2.0, 30.0, 40.0],
            "confidence": 0.88,
            "keypoints": [
                [5.0, 6.0, 0.9],
                [7.0, 8.0, 0.4],
            ],
        }
    )

    dumped = keyframe.model_dump()
    persisted = _keyframe_payload(keyframe)

    assert dumped["keypoints"] == [
        (5.0, 6.0, 0.9),
        (7.0, 8.0, 0.4),
    ]
    assert persisted["keypoints"] == [
        [5.0, 6.0, 0.9],
        [7.0, 8.0, 0.4],
    ]


def test_non_pose_tracking_keyframes_remain_backward_compatible() -> None:
    observation = TrackObservation(
        frame=1,
        provider_track_id=2,
        class_name="fish",
        confidence=0.8,
        bbox=(0.0, 0.0, 10.0, 10.0),
    )

    assert _keyframes([observation]) == [
        {
            "frame": 1,
            "bbox": [0.0, 0.0, 10.0, 10.0],
            "confidence": 0.8,
        }
    ]
