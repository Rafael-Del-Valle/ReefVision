"""Framework-neutral scientific metrics for anatomical pose evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, hypot, isfinite
from statistics import median

REFERENCE_VISIBILITY_STATES = frozenset(
    {"visible", "occluded", "absent", "uncertain", "out_of_frame"}
)


@dataclass(frozen=True, slots=True)
class PoseLandmarkReference:
    landmark_id: str
    name: str
    x: float
    y: float
    visibility: str


@dataclass(frozen=True, slots=True)
class PoseLandmarkEstimate:
    landmark_id: str
    x: float
    y: float
    confidence: float
    visible: bool


@dataclass(frozen=True, slots=True)
class PoseEvaluationInstance:
    instance_id: str
    references: tuple[PoseLandmarkReference, ...]
    estimates: tuple[PoseLandmarkEstimate, ...]
    normalization_length: float
    reference_area: float | None = None
    oks_sigmas: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class VisibilityMetrics:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float


@dataclass(frozen=True, slots=True)
class ConfidenceThresholdMetrics:
    threshold: float
    selected: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float


@dataclass(frozen=True, slots=True)
class ConfidenceCalibrationMetrics:
    sample_count: int
    correctness_threshold: float
    brier_score: float
    expected_calibration_error: float
    thresholds: tuple[ConfidenceThresholdMetrics, ...]


@dataclass(frozen=True, slots=True)
class PerLandmarkMetrics:
    landmark_id: str
    name: str
    visible_reference_count: int
    matched_visible_count: int
    localization_coverage: float
    mean_euclidean_error: float | None
    median_euclidean_error: float | None
    nme: float | None
    pck: dict[str, float]


@dataclass(frozen=True, slots=True)
class PoseEvaluationMetrics:
    instance_count: int
    visible_reference_count: int
    matched_visible_count: int
    localization_coverage: float
    mean_euclidean_error: float | None
    median_euclidean_error: float | None
    nme: float | None
    pck: dict[str, float]
    per_landmark: dict[str, PerLandmarkMetrics]
    visibility: VisibilityMetrics
    calibration: ConfidenceCalibrationMetrics
    oks: float | None
    oks_instance_count: int
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _LandmarkAccumulator:
    name: str
    reference_count: int
    matched_count: int
    errors: list[float]
    normalized_errors: list[float]
    pck_hits: dict[str, int]


def _threshold_key(value: float) -> str:
    return format(value, ".12g")


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _validate_thresholds(values: tuple[float, ...], label: str) -> tuple[float, ...]:
    if not values:
        raise ValueError(f"{label} must not be empty")
    normalized = tuple(float(value) for value in values)
    if any(not isfinite(value) or value < 0 or value > 1 for value in normalized):
        raise ValueError(f"{label} must contain finite values within [0, 1]")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must not contain duplicates")
    return normalized


def _validate_instance(instance: PoseEvaluationInstance) -> None:
    if not instance.instance_id:
        raise ValueError("Pose evaluation instance_id is required")
    if not isfinite(instance.normalization_length) or instance.normalization_length <= 0:
        raise ValueError("Pose normalization length must be finite and positive")
    reference_ids = [item.landmark_id for item in instance.references]
    estimate_ids = [item.landmark_id for item in instance.estimates]
    if not reference_ids or any(not item for item in reference_ids):
        raise ValueError("Pose evaluation requires identified reference landmarks")
    if len(reference_ids) != len(set(reference_ids)):
        raise ValueError("Reference landmark IDs must be unique per instance")
    if len(estimate_ids) != len(set(estimate_ids)):
        raise ValueError("Estimate landmark IDs must be unique per instance")
    for item in instance.references:
        if item.visibility not in REFERENCE_VISIBILITY_STATES:
            raise ValueError("Reference landmark visibility is invalid")
        if not item.name or not isfinite(item.x) or not isfinite(item.y):
            raise ValueError("Reference landmark values must be finite and identified")
    for item in instance.estimates:
        if not isfinite(item.x) or not isfinite(item.y):
            raise ValueError("Estimated landmark coordinates must be finite")
        if not isfinite(item.confidence) or not 0 <= item.confidence <= 1:
            raise ValueError("Estimated landmark confidence must be within [0, 1]")
    if instance.reference_area is not None and (
        not isfinite(instance.reference_area) or instance.reference_area <= 0
    ):
        raise ValueError("Reference area must be finite and positive")
    if instance.oks_sigmas is not None and any(
        not isfinite(value) or value <= 0 for value in instance.oks_sigmas.values()
    ):
        raise ValueError("OKS sigmas must be finite and positive")


def _confidence_metrics(
    samples: list[tuple[float, bool]],
    *,
    correctness_threshold: float,
    bin_count: int,
    thresholds: tuple[float, ...],
) -> ConfidenceCalibrationMetrics:
    if bin_count < 1 or bin_count > 1000:
        raise ValueError("Calibration bin count must be between 1 and 1000")
    if not samples:
        return ConfidenceCalibrationMetrics(
            sample_count=0,
            correctness_threshold=correctness_threshold,
            brier_score=0.0,
            expected_calibration_error=0.0,
            thresholds=tuple(
                ConfidenceThresholdMetrics(value, 0, 0, 0, 0, 0.0, 0.0) for value in thresholds
            ),
        )
    total = len(samples)
    positives = sum(int(correct) for _confidence, correct in samples)
    brier = sum((confidence - float(correct)) ** 2 for confidence, correct in samples) / total
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(bin_count)]
    for confidence, correct in samples:
        index = min(bin_count - 1, int(confidence * bin_count))
        bins[index].append((confidence, correct))
    ece = 0.0
    for items in bins:
        if not items:
            continue
        mean_confidence = sum(value for value, _correct in items) / len(items)
        accuracy = sum(int(correct) for _value, correct in items) / len(items)
        ece += (len(items) / total) * abs(accuracy - mean_confidence)
    curve: list[ConfidenceThresholdMetrics] = []
    for threshold in thresholds:
        selected = [
            (confidence, correct) for confidence, correct in samples if confidence >= threshold
        ]
        true_positives = sum(int(correct) for _confidence, correct in selected)
        false_positives = len(selected) - true_positives
        false_negatives = positives - true_positives
        curve.append(
            ConfidenceThresholdMetrics(
                threshold=threshold,
                selected=len(selected),
                true_positives=true_positives,
                false_positives=false_positives,
                false_negatives=false_negatives,
                precision=_rate(true_positives, len(selected)),
                recall=_rate(true_positives, positives),
            )
        )
    return ConfidenceCalibrationMetrics(
        sample_count=total,
        correctness_threshold=correctness_threshold,
        brier_score=brier,
        expected_calibration_error=ece,
        thresholds=tuple(curve),
    )


def evaluate_pose_instances(
    instances: list[PoseEvaluationInstance],
    *,
    pck_thresholds: tuple[float, ...] = (0.05, 0.1, 0.2),
    calibration_threshold: float = 0.1,
    calibration_bins: int = 10,
    confidence_thresholds: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 0.9),
) -> PoseEvaluationMetrics:
    """Evaluate stable-ID pose estimates against explicit reference anatomy.

    NME is reported over matched visible references and accompanied by localization
    coverage. PCK includes unmatched visible references as misses.
    """

    if not instances:
        raise ValueError("Pose evaluation requires at least one reference instance")
    pck_values = _validate_thresholds(pck_thresholds, "PCK thresholds")
    confidence_values = _validate_thresholds(confidence_thresholds, "Confidence thresholds")
    if not isfinite(calibration_threshold) or not 0 <= calibration_threshold <= 1:
        raise ValueError("Calibration correctness threshold must be within [0, 1]")

    errors: list[float] = []
    normalized_errors: list[float] = []
    pck_hits = {_threshold_key(value): 0 for value in pck_values}
    visible_reference_count = 0
    matched_visible_count = 0
    visibility_tp = visibility_fp = visibility_fn = visibility_tn = 0
    calibration_samples: list[tuple[float, bool]] = []
    accumulators: dict[str, _LandmarkAccumulator] = {}
    oks_values: list[float] = []
    oks_omitted = False

    for instance in instances:
        _validate_instance(instance)
        estimates = {item.landmark_id: item for item in instance.estimates}
        visible_references = [item for item in instance.references if item.visibility == "visible"]
        oks_ready = (
            instance.reference_area is not None
            and instance.oks_sigmas is not None
            and all(item.landmark_id in instance.oks_sigmas for item in visible_references)
        )
        oks_sum = 0.0

        for reference in instance.references:
            estimate = estimates.get(reference.landmark_id)
            predicted_visible = bool(estimate is not None and estimate.visible)
            reference_visible = reference.visibility == "visible"
            if reference_visible and predicted_visible:
                visibility_tp += 1
            elif reference_visible:
                visibility_fn += 1
            elif predicted_visible:
                visibility_fp += 1
            else:
                visibility_tn += 1
            if not reference_visible:
                continue

            visible_reference_count += 1
            accumulator = accumulators.setdefault(
                reference.landmark_id,
                _LandmarkAccumulator(
                    name=reference.name,
                    reference_count=0,
                    matched_count=0,
                    errors=[],
                    normalized_errors=[],
                    pck_hits={_threshold_key(value): 0 for value in pck_values},
                ),
            )
            if accumulator.name != reference.name:
                raise ValueError("Stable landmark ID maps to inconsistent names")
            accumulator.reference_count += 1
            confidence = estimate.confidence if estimate is not None else 0.0
            normalized_error: float | None = None
            if predicted_visible and estimate is not None:
                error = hypot(reference.x - estimate.x, reference.y - estimate.y)
                normalized_error = error / instance.normalization_length
                errors.append(error)
                normalized_errors.append(normalized_error)
                matched_visible_count += 1
                accumulator.matched_count += 1
                accumulator.errors.append(error)
                accumulator.normalized_errors.append(normalized_error)
                for threshold in pck_values:
                    key = _threshold_key(threshold)
                    if normalized_error <= threshold:
                        pck_hits[key] += 1
                        accumulator.pck_hits[key] += 1
                if oks_ready:
                    sigma = instance.oks_sigmas[reference.landmark_id]  # type: ignore[index]
                    oks_sum += exp(-(error**2) / (2 * sigma**2 * float(instance.reference_area)))
            calibration_samples.append(
                (
                    confidence,
                    normalized_error is not None and normalized_error <= calibration_threshold,
                )
            )
        if visible_references:
            if oks_ready:
                oks_values.append(oks_sum / len(visible_references))
            else:
                oks_omitted = True

    per_landmark = {
        landmark_id: PerLandmarkMetrics(
            landmark_id=landmark_id,
            name=item.name,
            visible_reference_count=item.reference_count,
            matched_visible_count=item.matched_count,
            localization_coverage=_rate(item.matched_count, item.reference_count),
            mean_euclidean_error=(sum(item.errors) / len(item.errors) if item.errors else None),
            median_euclidean_error=(median(item.errors) if item.errors else None),
            nme=(
                sum(item.normalized_errors) / len(item.normalized_errors)
                if item.normalized_errors
                else None
            ),
            pck={key: _rate(hits, item.reference_count) for key, hits in item.pck_hits.items()},
        )
        for landmark_id, item in sorted(accumulators.items())
    }
    warnings = (
        (
            (
                "OKS omitted for one or more instances because explicit positive "
                "reference area and per-landmark sigmas were not both available."
            ),
        )
        if oks_omitted
        else ()
    )
    return PoseEvaluationMetrics(
        instance_count=len(instances),
        visible_reference_count=visible_reference_count,
        matched_visible_count=matched_visible_count,
        localization_coverage=_rate(matched_visible_count, visible_reference_count),
        mean_euclidean_error=(sum(errors) / len(errors) if errors else None),
        median_euclidean_error=(median(errors) if errors else None),
        nme=(sum(normalized_errors) / len(normalized_errors) if normalized_errors else None),
        pck={key: _rate(hits, visible_reference_count) for key, hits in pck_hits.items()},
        per_landmark=per_landmark,
        visibility=VisibilityMetrics(
            true_positives=visibility_tp,
            false_positives=visibility_fp,
            false_negatives=visibility_fn,
            true_negatives=visibility_tn,
            precision=_rate(visibility_tp, visibility_tp + visibility_fp),
            recall=_rate(visibility_tp, visibility_tp + visibility_fn),
        ),
        calibration=_confidence_metrics(
            calibration_samples,
            correctness_threshold=calibration_threshold,
            bin_count=calibration_bins,
            thresholds=confidence_values,
        ),
        oks=(sum(oks_values) / len(oks_values) if oks_values else None),
        oks_instance_count=len(oks_values),
        warnings=warnings,
    )
