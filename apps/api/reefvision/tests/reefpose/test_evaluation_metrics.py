from __future__ import annotations

import math

import pytest

from reefvision.domain.pose_evaluation import (
    PoseEvaluationInstance,
    PoseLandmarkEstimate,
    PoseLandmarkReference,
    evaluate_pose_instances,
)


def _reference(
    landmark_id: str,
    x: float,
    y: float,
    *,
    visibility: str = "visible",
) -> PoseLandmarkReference:
    return PoseLandmarkReference(
        landmark_id=landmark_id,
        name=landmark_id,
        x=x,
        y=y,
        visibility=visibility,
    )


def _estimate(
    landmark_id: str,
    x: float,
    y: float,
    *,
    confidence: float = 1.0,
    visible: bool = True,
) -> PoseLandmarkEstimate:
    return PoseLandmarkEstimate(
        landmark_id=landmark_id,
        x=x,
        y=y,
        confidence=confidence,
        visible=visible,
    )


def test_exact_localization_pck_nme_and_per_landmark_metrics() -> None:
    result = evaluate_pose_instances(
        [
            PoseEvaluationInstance(
                instance_id="fish-1",
                references=(
                    _reference("snout", 0, 0),
                    _reference("tail", 10, 0),
                ),
                estimates=(
                    _estimate("snout", 3, 4, confidence=0.8),
                    _estimate("tail", 10, 0, confidence=0.9),
                ),
                normalization_length=10,
            )
        ],
        pck_thresholds=(0.1, 0.5),
        calibration_threshold=0.1,
        calibration_bins=2,
    )

    assert result.visible_reference_count == 2
    assert result.matched_visible_count == 2
    assert result.mean_euclidean_error == pytest.approx(2.5)
    assert result.median_euclidean_error == pytest.approx(2.5)
    assert result.nme == pytest.approx(0.25)
    assert result.pck == {"0.1": pytest.approx(0.5), "0.5": pytest.approx(1.0)}
    assert result.per_landmark["snout"].mean_euclidean_error == pytest.approx(5.0)
    assert result.per_landmark["snout"].pck["0.1"] == pytest.approx(0.0)
    assert result.per_landmark["tail"].pck["0.1"] == pytest.approx(1.0)


def test_missing_and_occluded_landmarks_are_visibility_aware() -> None:
    result = evaluate_pose_instances(
        [
            PoseEvaluationInstance(
                instance_id="fish-1",
                references=(
                    _reference("snout", 1, 1),
                    _reference("tail", 9, 1),
                    _reference("fin", 5, 5, visibility="occluded"),
                ),
                estimates=(
                    _estimate("snout", 1, 1, confidence=0.9),
                    _estimate("tail", 0, 0, confidence=0.0, visible=False),
                    _estimate("fin", 5, 5, confidence=0.7),
                ),
                normalization_length=10,
            )
        ],
        pck_thresholds=(0.2,),
    )

    assert result.visible_reference_count == 2
    assert result.matched_visible_count == 1
    assert result.localization_coverage == pytest.approx(0.5)
    assert result.pck["0.2"] == pytest.approx(0.5)
    assert result.mean_euclidean_error == pytest.approx(0.0)
    assert result.nme == pytest.approx(0.0)
    assert result.visibility.true_positives == 1
    assert result.visibility.false_positives == 1
    assert result.visibility.false_negatives == 1
    assert result.visibility.true_negatives == 0
    assert result.visibility.precision == pytest.approx(0.5)
    assert result.visibility.recall == pytest.approx(0.5)


def test_confidence_calibration_and_threshold_curve_include_misses() -> None:
    result = evaluate_pose_instances(
        [
            PoseEvaluationInstance(
                instance_id="fish-1",
                references=(
                    _reference("a", 0, 0),
                    _reference("b", 10, 0),
                    _reference("c", 20, 0),
                ),
                estimates=(
                    _estimate("a", 0, 0, confidence=0.9),
                    _estimate("b", 15, 0, confidence=0.8),
                ),
                normalization_length=10,
            )
        ],
        pck_thresholds=(0.1,),
        calibration_threshold=0.1,
        calibration_bins=2,
        confidence_thresholds=(0.0, 0.85, 0.95),
    )

    # Correctness targets are [1, 0, 0], confidences [0.9, 0.8, 0.0].
    assert result.calibration.brier_score == pytest.approx((0.1**2 + 0.8**2) / 3)
    assert result.calibration.expected_calibration_error == pytest.approx(
        (1 / 3) * 0 + (2 / 3) * abs(0.5 - 0.85)
    )
    zero, middle, high = result.calibration.thresholds
    assert (zero.selected, zero.true_positives, zero.false_positives) == (3, 1, 2)
    assert (middle.selected, middle.true_positives, middle.false_positives) == (1, 1, 0)
    assert (high.selected, high.true_positives, high.false_positives) == (0, 0, 0)


def test_confidence_calibration_includes_false_positive_visibility() -> None:
    result = evaluate_pose_instances(
        [
            PoseEvaluationInstance(
                instance_id="fish-1",
                references=(
                    _reference("snout", 0, 0),
                    _reference("fin", 5, 5, visibility="absent"),
                ),
                estimates=(
                    _estimate("snout", 0, 0, confidence=0.9),
                    _estimate("fin", 5, 5, confidence=1.0),
                ),
                normalization_length=10,
            )
        ],
        calibration_threshold=0.1,
        confidence_thresholds=(0.0,),
    )

    assert result.visibility.false_positives == 1
    assert result.calibration.sample_count == 2
    assert result.calibration.brier_score == pytest.approx((0.1**2 + 1.0**2) / 2)
    assert result.calibration.thresholds[0].precision == pytest.approx(0.5)


def test_oks_requires_valid_sigmas_and_area() -> None:
    valid = evaluate_pose_instances(
        [
            PoseEvaluationInstance(
                instance_id="fish-1",
                references=(_reference("snout", 0, 0),),
                estimates=(_estimate("snout", 1, 0),),
                normalization_length=10,
                reference_area=100,
                oks_sigmas={"snout": 0.1},
            )
        ]
    )
    assert valid.oks == pytest.approx(math.exp(-0.5))
    assert valid.oks_instance_count == 1
    assert not valid.warnings

    omitted = evaluate_pose_instances(
        [
            PoseEvaluationInstance(
                instance_id="fish-2",
                references=(_reference("snout", 0, 0),),
                estimates=(_estimate("snout", 0, 0),),
                normalization_length=10,
            )
        ]
    )
    assert omitted.oks is None
    assert omitted.oks_instance_count == 0
    assert any("OKS omitted" in warning for warning in omitted.warnings)


@pytest.mark.parametrize(
    "instance",
    [
        PoseEvaluationInstance(
            instance_id="bad-normalization",
            references=(_reference("a", 0, 0),),
            estimates=(),
            normalization_length=0,
        ),
        PoseEvaluationInstance(
            instance_id="duplicate",
            references=(_reference("a", 0, 0), _reference("a", 1, 1)),
            estimates=(),
            normalization_length=1,
        ),
    ],
)
def test_invalid_scientific_inputs_fail_closed(instance: PoseEvaluationInstance) -> None:
    with pytest.raises(ValueError):
        evaluate_pose_instances([instance])
