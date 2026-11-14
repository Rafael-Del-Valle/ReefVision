from __future__ import annotations

import pytest

from reefvision.domain.pose_identity_tracking import (
    AssociationConfig,
    Landmark,
    PoseDetection,
    associate_pose_identities,
)


def _detection(
    detection_id: str,
    frame: int,
    x: float,
    *,
    confidence: float = 0.95,
    landmark_x: float | None = None,
) -> PoseDetection:
    landmarks = (
        ()
        if landmark_x is None
        else (
            Landmark(
                landmark_id="nose",
                x=landmark_x,
                y=15.0,
                confidence=confidence,
                visibility="visible",
            ),
        )
    )
    return PoseDetection(
        detection_id=detection_id,
        source_track_id=f"source-{detection_id}",
        frame_index=frame,
        bbox=(x, 10.0, 20.0, 10.0),
        landmarks=landmarks,
        confidence=confidence,
    )


def test_association_is_deterministic_for_equal_candidates() -> None:
    detections = [
        _detection("z-first", 0, 0),
        _detection("a-first", 0, 0),
        _detection("z-next", 1, 1),
        _detection("a-next", 1, 1),
    ]

    forward = associate_pose_identities(detections, AssociationConfig())
    reverse = associate_pose_identities(list(reversed(detections)), AssociationConfig())

    expected = {
        "a-first": "animal-0001",
        "z-first": "animal-0002",
        "a-next": "animal-0001",
        "z-next": "animal-0002",
    }
    assert {item.detection_id: item.identity_key for item in forward.assignments} == expected
    assert {item.detection_id: item.identity_key for item in reverse.assignments} == expected
    assert forward.parameters_sha256 == reverse.parameters_sha256


def test_motion_history_preserves_identities_through_crossing() -> None:
    result = associate_pose_identities(
        [
            _detection("left-0", 0, 0),
            _detection("right-0", 0, 100),
            _detection("left-1", 1, 30),
            _detection("right-1", 1, 70),
            _detection("left-2", 2, 60),
            _detection("right-2", 2, 40),
        ],
        AssociationConfig(
            proximity_weight=0.05,
            overlap_weight=0.0,
            landmark_weight=0.0,
            motion_weight=0.95,
            confidence_weight=0.0,
            acceptance_threshold=2.0,
            max_normalized_distance=5.0,
        ),
    )

    assignments = {item.detection_id: item.identity_key for item in result.assignments}
    assert assignments["left-0"] == assignments["left-1"] == assignments["left-2"]
    assert assignments["right-0"] == assignments["right-1"] == assignments["right-2"]
    selected = [item for item in result.decisions if item.selected and item.frame_index == 2]
    assert len(selected) == 2
    assert all(
        set(item.score_components)
        == {
            "proximity_cost",
            "overlap_cost",
            "landmark_cost",
            "motion_cost",
            "confidence_cost",
        }
        for item in selected
    )


def test_temporary_occlusion_reuses_identity_and_records_interval() -> None:
    result = associate_pose_identities(
        [
            _detection("fish-0", 0, 0),
            _detection("fish-1", 1, 10),
            _detection("fish-4", 4, 40),
        ],
        AssociationConfig(
            max_gap_frames=3,
            max_normalized_distance=5.0,
            acceptance_threshold=1.5,
        ),
    )

    assignments = {item.detection_id: item.identity_key for item in result.assignments}
    assert assignments == {
        "fish-0": "animal-0001",
        "fish-1": "animal-0001",
        "fish-4": "animal-0001",
    }
    assert [
        (item.identity_key, item.start_frame, item.end_frame) for item in result.occlusions
    ] == [("animal-0001", 2, 3)]


def test_missing_landmarks_fall_back_to_geometry_without_inventing_similarity() -> None:
    result = associate_pose_identities(
        [
            _detection("fish-0", 0, 0, landmark_x=5),
            _detection("fish-1", 1, 2),
        ],
        AssociationConfig(max_normalized_distance=3.0, acceptance_threshold=1.0),
    )

    selected = next(item for item in result.decisions if item.selected)
    assert selected.score_components["landmark_cost"] is None
    assert result.assignments[0].identity_key == result.assignments[1].identity_key


def test_landmark_only_matching_without_shared_landmarks_is_gated_without_crashing() -> None:
    result = associate_pose_identities(
        [_detection("fish-0", 0, 0, landmark_x=5), _detection("fish-1", 1, 2)],
        AssociationConfig(
            proximity_weight=0.0,
            overlap_weight=0.0,
            landmark_weight=1.0,
            motion_weight=0.0,
            confidence_weight=0.0,
        ),
    )

    rejected = next(
        item for item in result.decisions if item.detection_id == "fish-1" and not item.selected
    )
    assert rejected.gate_reason == "missing_weighted_evidence"
    assert result.assignments[0].identity_key != result.assignments[1].identity_key


def test_association_checks_cancellation_between_frames() -> None:
    checks = 0

    def cancellation_check() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        associate_pose_identities(
            [_detection("fish-0", 0, 0), _detection("fish-1", 1, 2)],
            AssociationConfig(),
            cancellation_check=cancellation_check,
        )
    assert checks == 2


def test_uncertain_detection_is_rejected_without_starting_an_identity() -> None:
    result = associate_pose_identities(
        [_detection("uncertain", 0, 0, confidence=0.1)],
        AssociationConfig(minimum_detection_confidence=0.5),
    )

    assert len(result.identities) == 0
    assert result.assignments[0].identity_key is None
    assert result.assignments[0].state == "rejected_low_confidence"


def test_track_terminates_after_configured_gap() -> None:
    result = associate_pose_identities(
        [_detection("old", 0, 0), _detection("new", 4, 1)],
        AssociationConfig(max_gap_frames=2, acceptance_threshold=2.0),
    )

    assert [item.identity_key for item in result.identities] == ["animal-0001", "animal-0002"]
    assert result.identities[0].lifecycle_state == "terminated"
    assert result.identities[0].last_frame == 0
    assert result.identities[1].lifecycle_state == "active"


def test_parameter_hash_changes_only_when_configuration_changes() -> None:
    detection = _detection("fish", 0, 0)
    first = associate_pose_identities([detection], AssociationConfig(max_gap_frames=2))
    same = associate_pose_identities([detection], AssociationConfig(max_gap_frames=2))
    changed = associate_pose_identities([detection], AssociationConfig(max_gap_frames=3))

    assert first.parameters_sha256 == same.parameters_sha256
    assert first.parameters_sha256 != changed.parameters_sha256
    assert len(first.parameters_sha256) == 64
