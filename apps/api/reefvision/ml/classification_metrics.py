"""Provider-free multiclass reliability, curve, threshold, and calibration metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class BinaryCurvePoint:
    threshold: float
    true_positive_rate: float
    false_positive_rate: float
    precision: float
    recall: float


@dataclass(frozen=True)
class IsotonicBlock:
    lower_confidence: float
    upper_confidence: float
    calibrated_probability: float
    count: int


def multiclass_matthews(confusion: NDArray[Any]) -> float:
    matrix = np.asarray(confusion, dtype=np.float64)
    total = float(matrix.sum())
    if total <= 0:
        return 0.0
    true_positive_sum = float(np.trace(matrix))
    predicted = matrix.sum(axis=0)
    actual = matrix.sum(axis=1)
    numerator = true_positive_sum * total - float(np.dot(predicted, actual))
    denominator = math.sqrt(
        max(total * total - float(np.dot(predicted, predicted)), 0)
        * max(total * total - float(np.dot(actual, actual)), 0)
    )
    return numerator / denominator if denominator else 0.0


def cohen_kappa(confusion: NDArray[Any]) -> float:
    matrix = np.asarray(confusion, dtype=np.float64)
    total = float(matrix.sum())
    if total <= 0:
        return 0.0
    observed = float(np.trace(matrix)) / total
    expected = float(np.dot(matrix.sum(axis=0), matrix.sum(axis=1))) / (total * total)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def binary_curve(
    scores: Sequence[float],
    targets: Sequence[bool],
) -> list[BinaryCurvePoint]:
    if len(scores) != len(targets):
        raise ValueError("Curve scores and targets must have equal length")
    thresholds = sorted({0.0, 1.0, *(float(score) for score in scores)}, reverse=True)
    positive_count = sum(bool(target) for target in targets)
    negative_count = len(targets) - positive_count
    points: list[BinaryCurvePoint] = []
    for threshold in thresholds:
        predicted = [float(score) >= threshold for score in scores]
        true_positives = sum(
            prediction and target for prediction, target in zip(predicted, targets, strict=True)
        )
        false_positives = sum(
            prediction and not target for prediction, target in zip(predicted, targets, strict=True)
        )
        false_negatives = positive_count - true_positives
        tpr = true_positives / positive_count if positive_count else 0.0
        fpr = false_positives / negative_count if negative_count else 0.0
        precision = (
            true_positives / (true_positives + false_positives)
            if true_positives + false_positives
            else 0.0
        )
        recall = (
            true_positives / (true_positives + false_negatives)
            if true_positives + false_negatives
            else 0.0
        )
        points.append(BinaryCurvePoint(threshold, tpr, fpr, precision, recall))
    return points


def trapezoid_auc(points: Sequence[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    ordered = sorted((float(x), float(y)) for x, y in points)
    return float(
        sum(
            (ordered[index][0] - ordered[index - 1][0])
            * (ordered[index][1] + ordered[index - 1][1])
            / 2
            for index in range(1, len(ordered))
        )
    )


def roc_auc(curve: Sequence[BinaryCurvePoint]) -> float | None:
    return trapezoid_auc([(point.false_positive_rate, point.true_positive_rate) for point in curve])


def precision_recall_auc(curve: Sequence[BinaryCurvePoint]) -> float | None:
    return trapezoid_auc([(point.recall, point.precision) for point in curve])


def optimal_f1_threshold(curve: Sequence[BinaryCurvePoint]) -> tuple[float, float]:
    best_threshold = 0.0
    best_f1 = 0.0
    for point in curve:
        f1 = (
            2 * point.precision * point.recall / (point.precision + point.recall)
            if point.precision + point.recall
            else 0.0
        )
        if f1 > best_f1 or (math.isclose(f1, best_f1) and point.threshold > best_threshold):
            best_threshold, best_f1 = point.threshold, f1
    return best_threshold, best_f1


def top_k_accuracy(
    probability_rows: Sequence[dict[str, float]],
    actual_labels: Sequence[str],
    *,
    k: int,
) -> float | None:
    if len(probability_rows) != len(actual_labels) or not probability_rows:
        return None
    usable = 0
    correct = 0
    for probabilities, actual in zip(probability_rows, actual_labels, strict=True):
        if not probabilities:
            continue
        usable += 1
        top = {
            label
            for label, _score in sorted(
                probabilities.items(),
                key=lambda item: (-float(item[1]), item[0]),
            )[:k]
        }
        correct += actual in top
    return correct / usable if usable else None


def temperature_scale_probabilities(
    probability_rows: Sequence[dict[str, float]],
    actual_labels: Sequence[str],
    *,
    temperatures: Sequence[float] | None = None,
) -> tuple[float, float | None]:
    """Grid-search a scalar temperature using stored probability vectors."""

    candidates = temperatures or tuple(np.geomspace(0.25, 8.0, 81))
    labels = sorted({label for row in probability_rows for label in row})
    if not labels or len(probability_rows) != len(actual_labels):
        return 1.0, None
    best_temperature = 1.0
    best_loss = math.inf
    epsilon = 1e-12
    for temperature in candidates:
        if temperature <= 0:
            continue
        losses: list[float] = []
        for row, actual in zip(probability_rows, actual_labels, strict=True):
            if actual not in row:
                continue
            probabilities = np.asarray([max(float(row.get(label, 0)), epsilon) for label in labels])
            logits = np.log(probabilities)
            scaled = logits / float(temperature)
            scaled -= scaled.max()
            normalized = np.exp(scaled)
            normalized /= normalized.sum()
            losses.append(-math.log(max(float(normalized[labels.index(actual)]), epsilon)))
        if losses and (loss := sum(losses) / len(losses)) < best_loss:
            best_temperature, best_loss = float(temperature), float(loss)
    return best_temperature, None if not math.isfinite(best_loss) else best_loss


def isotonic_correctness(
    confidences: Sequence[float],
    correct: Sequence[bool],
) -> list[IsotonicBlock]:
    """Fit pool-adjacent-violators calibration blocks to top-label correctness."""

    if len(confidences) != len(correct):
        raise ValueError("Isotonic inputs must have equal length")
    ordered = sorted(
        (float(confidence), float(outcome))
        for confidence, outcome in zip(confidences, correct, strict=True)
    )
    blocks: list[dict[str, float | int]] = [
        {"lower": confidence, "upper": confidence, "sum": outcome, "count": 1}
        for confidence, outcome in ordered
    ]
    index = 0
    while index < len(blocks) - 1:
        left = blocks[index]
        right = blocks[index + 1]
        left_mean = float(left["sum"]) / int(left["count"])
        right_mean = float(right["sum"]) / int(right["count"])
        if left_mean <= right_mean:
            index += 1
            continue
        merged = {
            "lower": left["lower"],
            "upper": right["upper"],
            "sum": float(left["sum"]) + float(right["sum"]),
            "count": int(left["count"]) + int(right["count"]),
        }
        blocks[index : index + 2] = [merged]
        index = max(index - 1, 0)
    return [
        IsotonicBlock(
            lower_confidence=float(block["lower"]),
            upper_confidence=float(block["upper"]),
            calibrated_probability=float(block["sum"]) / int(block["count"]),
            count=int(block["count"]),
        )
        for block in blocks
    ]
