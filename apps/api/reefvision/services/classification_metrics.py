"""Reusable single-label classification performance and calibration metrics."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt
from statistics import mean
from typing import Iterable

from reefvision.schemas.classification_evaluation import (
    ClassificationCalibrationBin,
    ClassificationClassEvaluation,
    ClassificationConfusionCell,
    ClassificationCurvePoint,
    ClassificationEvaluationResponse,
    ClassificationIsotonicBlock,
    ClassificationTopKAccuracy,
)


@dataclass(frozen=True, slots=True)
class ClassificationObservation:
    actual_label_class_id: str
    predicted_label_class_id: str
    confidence: float
    probabilities_by_class_id: dict[str, float]

    @property
    def correct(self) -> bool:
        return self.actual_label_class_id == self.predicted_label_class_id


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _trapezoid_area(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    ordered = sorted(points)
    area = 0.0
    previous_x, previous_y = ordered[0]
    for current_x, current_y in ordered[1:]:
        if current_x < previous_x:
            continue
        area += (current_x - previous_x) * (current_y + previous_y) / 2.0
        previous_x, previous_y = current_x, current_y
    return max(0.0, min(1.0, area))


def _class_curve(
    observations: list[ClassificationObservation],
    class_id: str,
) -> tuple[list[ClassificationCurvePoint], float | None, float | None, float | None, float | None]:
    positives = sum(item.actual_label_class_id == class_id for item in observations)
    negatives = len(observations) - positives
    if positives == 0:
        return [], None, None, None, None
    scores = [
        max(0.0, min(1.0, float(item.probabilities_by_class_id.get(class_id, 0.0))))
        for item in observations
    ]
    thresholds = sorted({1.0, 0.0, *scores}, reverse=True)
    curve: list[ClassificationCurvePoint] = []
    best_threshold: float | None = None
    best_f1: float | None = None
    for threshold in thresholds:
        true_positive = false_positive = false_negative = 0
        for observation, score in zip(observations, scores, strict=True):
            positive = score >= threshold
            actual_positive = observation.actual_label_class_id == class_id
            if positive and actual_positive:
                true_positive += 1
            elif positive:
                false_positive += 1
            elif actual_positive:
                false_negative += 1
        true_positive_rate = _safe_divide(true_positive, positives)
        false_positive_rate = _safe_divide(false_positive, negatives)
        precision = _safe_divide(true_positive, true_positive + false_positive)
        recall = _safe_divide(true_positive, true_positive + false_negative)
        f1 = _safe_divide(2.0 * precision * recall, precision + recall)
        if best_f1 is None or f1 > best_f1 or (
            f1 == best_f1 and best_threshold is not None and threshold > best_threshold
        ):
            best_f1 = f1
            best_threshold = threshold
        curve.append(
            ClassificationCurvePoint(
                threshold=threshold,
                true_positive_rate=true_positive_rate,
                false_positive_rate=false_positive_rate,
                precision=precision,
                recall=recall,
            )
        )
    roc_auc = (
        _trapezoid_area([(item.false_positive_rate, item.true_positive_rate) for item in curve])
        if negatives > 0
        else None
    )
    precision_recall_auc = _trapezoid_area([(item.recall, item.precision) for item in curve])
    return curve, roc_auc, precision_recall_auc, best_threshold, best_f1


def _mcc(confusion: dict[tuple[str, str], int], classes: set[str], sample_count: int) -> float:
    if sample_count <= 0:
        return 0.0
    actual = {
        class_id: sum(
            count for (actual_id, _predicted_id), count in confusion.items() if actual_id == class_id
        )
        for class_id in classes
    }
    predicted = {
        class_id: sum(
            count for (_actual_id, predicted_id), count in confusion.items() if predicted_id == class_id
        )
        for class_id in classes
    }
    correct = sum(confusion.get((class_id, class_id), 0) for class_id in classes)
    cross = sum(actual[class_id] * predicted[class_id] for class_id in classes)
    numerator = correct * sample_count - cross
    denominator = sqrt(
        (sample_count * sample_count - sum(value * value for value in predicted.values()))
        * (sample_count * sample_count - sum(value * value for value in actual.values()))
    )
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def _kappa(confusion: dict[tuple[str, str], int], classes: set[str], sample_count: int) -> float:
    if sample_count <= 0:
        return 0.0
    actual = {
        class_id: sum(
            count for (actual_id, _predicted_id), count in confusion.items() if actual_id == class_id
        )
        for class_id in classes
    }
    predicted = {
        class_id: sum(
            count for (_actual_id, predicted_id), count in confusion.items() if predicted_id == class_id
        )
        for class_id in classes
    }
    observed = sum(confusion.get((class_id, class_id), 0) for class_id in classes) / sample_count
    expected = sum(actual[class_id] * predicted[class_id] for class_id in classes) / float(
        sample_count * sample_count
    )
    if 1.0 - expected <= 0:
        return 0.0
    return max(-1.0, min(1.0, (observed - expected) / (1.0 - expected)))


def _temperature_calibration(
    observations: list[ClassificationObservation],
    classes: list[str],
) -> tuple[float | None, float | None]:
    if not observations or len(classes) < 2:
        return None, None
    eps = 1e-12

    def nll(temperature: float) -> float:
        total = 0.0
        for observation in observations:
            logits = [
                log(max(eps, observation.probabilities_by_class_id.get(class_id, 0.0)))
                / temperature
                for class_id in classes
            ]
            maximum = max(logits)
            exponentials = [exp(value - maximum) for value in logits]
            denominator = sum(exponentials)
            true_index = classes.index(observation.actual_label_class_id)
            probability = exponentials[true_index] / denominator
            total -= log(max(eps, probability))
        return total / len(observations)

    # Deterministic logarithmic search is sufficient for post-hoc reporting and avoids a
    # heavyweight optimizer dependency in the packaged desktop runtime.
    candidates = [0.05 * (100.0 ** (index / 199.0)) for index in range(200)]
    scored = [(nll(value), value) for value in candidates]
    best_nll, best_temperature = min(scored)
    return best_temperature, best_nll


def _isotonic_blocks(observations: list[ClassificationObservation]) -> list[ClassificationIsotonicBlock]:
    if not observations:
        return []
    ordered = sorted(observations, key=lambda item: item.confidence)
    blocks: list[dict[str, float | int]] = []
    for observation in ordered:
        blocks.append(
            {
                "lower": float(observation.confidence),
                "upper": float(observation.confidence),
                "sum": float(observation.correct),
                "count": 1,
            }
        )
        while len(blocks) >= 2:
            previous = blocks[-2]
            current = blocks[-1]
            previous_probability = float(previous["sum"]) / int(previous["count"])
            current_probability = float(current["sum"]) / int(current["count"])
            if previous_probability <= current_probability:
                break
            merged = {
                "lower": float(previous["lower"]),
                "upper": float(current["upper"]),
                "sum": float(previous["sum"]) + float(current["sum"]),
                "count": int(previous["count"]) + int(current["count"]),
            }
            blocks[-2:] = [merged]
    return [
        ClassificationIsotonicBlock(
            lower_confidence=float(block["lower"]),
            upper_confidence=float(block["upper"]),
            calibrated_probability=float(block["sum"]) / int(block["count"]),
            count=int(block["count"]),
        )
        for block in blocks
    ]


def build_classification_evaluation(
    *,
    project_id: str,
    model_id: str,
    observations: Iterable[ClassificationObservation],
    calibration_bin_count: int = 10,
    top_k_values: Iterable[int] = (1, 3, 5),
    include_curves: bool = True,
    warnings: Iterable[str] = (),
) -> ClassificationEvaluationResponse:
    rows = list(observations)
    sample_count = len(rows)
    confusion: dict[tuple[str, str], int] = {}
    classes = {
        item.actual_label_class_id for item in rows
    } | {item.predicted_label_class_id for item in rows}
    for item in rows:
        key = (item.actual_label_class_id, item.predicted_label_class_id)
        confusion[key] = confusion.get(key, 0) + 1
    ordered_classes = sorted(classes)

    per_class: list[ClassificationClassEvaluation] = []
    for class_id in ordered_classes:
        support = sum(
            count for (actual, _predicted), count in confusion.items() if actual == class_id
        )
        predicted_count = sum(
            count for (_actual, predicted), count in confusion.items() if predicted == class_id
        )
        true_positive = confusion.get((class_id, class_id), 0)
        false_positive = predicted_count - true_positive
        false_negative = support - true_positive
        true_negative = sample_count - true_positive - false_positive - false_negative
        precision = _safe_divide(true_positive, predicted_count)
        recall = _safe_divide(true_positive, support)
        specificity = _safe_divide(true_negative, true_negative + false_positive)
        negative_predictive_value = _safe_divide(
            true_negative,
            true_negative + false_negative,
        )
        f1 = _safe_divide(2.0 * precision * recall, precision + recall)
        curve, roc_auc, pr_auc, optimal_threshold, optimal_f1 = _class_curve(rows, class_id)
        per_class.append(
            ClassificationClassEvaluation(
                label_class_id=class_id,
                support=support,
                predicted_count=predicted_count,
                true_positive_count=true_positive,
                true_negative_count=true_negative,
                false_positive_count=false_positive,
                false_negative_count=false_negative,
                precision=precision,
                recall=recall,
                sensitivity=recall,
                specificity=specificity,
                negative_predictive_value=negative_predictive_value,
                balanced_accuracy=(recall + specificity) / 2.0,
                f1=f1,
                roc_auc=roc_auc,
                precision_recall_auc=pr_auc,
                optimal_f1_threshold=optimal_threshold,
                optimal_f1=optimal_f1,
                curve=curve if include_curves else [],
            )
        )

    correct_count = sum(item.correct for item in rows)
    accuracy = _safe_divide(correct_count, sample_count)
    macro_precision = mean(item.precision for item in per_class) if per_class else 0.0
    macro_recall = mean(item.recall for item in per_class) if per_class else 0.0
    macro_f1 = mean(item.f1 for item in per_class) if per_class else 0.0
    weighted_f1 = (
        sum(item.f1 * item.support for item in per_class) / sample_count if sample_count else 0.0
    )

    calibration_bins: list[ClassificationCalibrationBin] = []
    expected_calibration_error = 0.0
    for index in range(calibration_bin_count):
        lower = index / calibration_bin_count
        upper = (index + 1) / calibration_bin_count
        selected = [
            item
            for item in rows
            if item.confidence >= lower
            and (item.confidence < upper or (index == calibration_bin_count - 1 and item.confidence <= 1))
        ]
        if selected:
            average_confidence = mean(item.confidence for item in selected)
            bin_accuracy = mean(float(item.correct) for item in selected)
            absolute_gap = abs(bin_accuracy - average_confidence)
            expected_calibration_error += (
                len(selected) / sample_count * absolute_gap if sample_count else 0.0
            )
        else:
            average_confidence = None
            bin_accuracy = None
            absolute_gap = None
        calibration_bins.append(
            ClassificationCalibrationBin(
                lower_bound=lower,
                upper_bound=upper,
                sample_count=len(selected),
                mean_confidence=average_confidence,
                accuracy=bin_accuracy,
                absolute_gap=absolute_gap,
            )
        )

    top_k: list[ClassificationTopKAccuracy] = []
    for raw_k in sorted(set(int(value) for value in top_k_values if int(value) >= 1)):
        if not rows:
            top_k.append(ClassificationTopKAccuracy(k=raw_k, accuracy=None))
            continue
        hits = 0
        usable = 0
        for item in rows:
            if not item.probabilities_by_class_id:
                continue
            usable += 1
            ranked = sorted(
                item.probabilities_by_class_id,
                key=item.probabilities_by_class_id.get,
                reverse=True,
            )[:raw_k]
            hits += item.actual_label_class_id in ranked
        top_k.append(
            ClassificationTopKAccuracy(
                k=raw_k,
                accuracy=(hits / usable if usable else None),
            )
        )

    top_label_brier = (
        mean((item.confidence - float(item.correct)) ** 2 for item in rows) if rows else None
    )
    temperature, temperature_nll = _temperature_calibration(rows, ordered_classes)
    return ClassificationEvaluationResponse(
        project_id=project_id,
        model_id=model_id,
        sample_count=sample_count,
        correct_count=correct_count,
        accuracy=accuracy,
        balanced_accuracy=macro_recall,
        macro_precision=macro_precision,
        macro_recall=macro_recall,
        macro_f1=macro_f1,
        weighted_f1=weighted_f1,
        matthews_correlation_coefficient=_mcc(confusion, classes, sample_count),
        cohen_kappa=_kappa(confusion, classes, sample_count),
        mean_confidence=(mean(item.confidence for item in rows) if rows else None),
        expected_calibration_error=(expected_calibration_error if rows else None),
        top_label_brier_score=top_label_brier,
        temperature_scale=temperature,
        temperature_scaled_negative_log_likelihood=temperature_nll,
        confidence_threshold=0.0,
        review_statuses=[],
        top_k_accuracy=top_k,
        per_class=per_class,
        confusion_matrix=[
            ClassificationConfusionCell(
                actual_label_class_id=actual,
                predicted_label_class_id=predicted,
                count=count,
            )
            for (actual, predicted), count in sorted(confusion.items())
        ],
        calibration_bins=calibration_bins,
        isotonic_calibration=_isotonic_blocks(rows),
        warnings=list(warnings),
    )
