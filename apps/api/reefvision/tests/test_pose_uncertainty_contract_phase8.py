from __future__ import annotations

from reefvision.jobs.video_tracking import _keyframes
from reefvision.ml.video_tracking import (
    TrackObservation,
    build_pose_uncertainty_evidence,
)


def test_current_pose_uncertainty_contract_does_not_invent_heatmap_or_paf() -> None:
    evidence = build_pose_uncertainty_evidence(
        provider_id="ultralytics",
        provider_version="test",
        keypoints=(
            (10.0, 20.0, 0.90),
            (15.0, 25.0, 0.40),
        ),
    )

    assert evidence["capabilities"] == {
        "keypoint_confidence": True,
        "heatmap_entropy": False,
        "paf_ambiguity": False,
    }
    assert evidence["available_signals"] == ["keypoint_confidence"]
    assert evidence["heatmap_entropy"] is None
    assert evidence["paf_ambiguity"] is None
    assert evidence["mean_keypoint_confidence"] == 0.65
    assert evidence["minimum_keypoint_confidence"] == 0.40


def test_provider_native_heatmap_and_paf_scores_are_explicit_when_supplied() -> None:
    evidence = build_pose_uncertainty_evidence(
        provider_id="future_pose_provider",
        provider_version="1.0",
        keypoints=((10.0, 20.0, 0.90),),
        heatmap_entropy=0.72,
        paf_ambiguity=0.44,
    )

    assert evidence["capabilities"]["heatmap_entropy"] is True
    assert evidence["capabilities"]["paf_ambiguity"] is True
    assert evidence["heatmap_entropy"] == 0.72
    assert evidence["paf_ambiguity"] == 0.44


def test_video_keyframe_persists_pose_uncertainty_evidence() -> None:
    evidence = build_pose_uncertainty_evidence(
        provider_id="sleap_nn",
        provider_version="0.3.3",
        keypoints=(
            (20.0, 30.0, 0.92),
            (40.0, 50.0, 0.71),
        ),
    )

    observation = TrackObservation(
        frame=3,
        provider_track_id=7,
        class_name="jellyfish",
        confidence=0.85,
        bbox=(10.0, 10.0, 80.0, 70.0),
        keypoints=(
            (20.0, 30.0, 0.92),
            (40.0, 50.0, 0.71),
        ),
        pose_uncertainty=evidence,
    )

    keyframes = _keyframes(
        [observation],
        {
            "expanded_labels": [
                "bell_center",
                "tentacle",
            ]
        },
    )

    assert len(keyframes) == 1
    persisted = keyframes[0]["pose_uncertainty"]

    assert persisted == evidence
    assert persisted["provider_id"] == "sleap_nn"
    assert persisted["capabilities"]["heatmap_entropy"] is False
    assert persisted["capabilities"]["paf_ambiguity"] is False
