"""Advanced segmentation boundary, panoptic, size, calibration, and sweep metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image

from reefvision.ml.mask_tools import erode


@dataclass(frozen=True)
class BoundaryMetrics:
    precision: float
    recall: float
    f1: float
    hausdorff_distance: float | None
    average_symmetric_surface_distance: float | None


@dataclass(frozen=True)
class PanopticMetrics:
    panoptic_quality: float
    segmentation_quality: float
    recognition_quality: float


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_confidence: float | None
    empirical_match_rate: float | None
    calibration_gap: float | None


def as_binary(mask: np.ndarray | Image.Image) -> np.ndarray:
    array = np.asarray(mask if isinstance(mask, np.ndarray) else mask.convert("L"))
    if array.ndim != 2:
        raise ValueError("Segmentation metric masks must be two-dimensional")
    return array > 0


def boundary(mask: np.ndarray | Image.Image) -> np.ndarray:
    values = as_binary(mask)
    if not values.any():
        return values.copy()
    return values & ~erode(values, radius=1)


def _coordinates(mask: np.ndarray) -> np.ndarray:
    return np.column_stack(np.nonzero(mask)).astype(np.float64, copy=False)


def _directed_nearest_distances(
    source: np.ndarray,
    target: np.ndarray,
    *,
    chunk_size: int = 2048,
) -> np.ndarray:
    if source.size == 0:
        return np.empty((0,), dtype=np.float64)
    if target.size == 0:
        return np.full((len(source),), math.inf, dtype=np.float64)
    output = np.empty((len(source),), dtype=np.float64)
    for start in range(0, len(source), chunk_size):
        chunk = source[start : start + chunk_size]
        differences = chunk[:, None, :] - target[None, :, :]
        squared = np.sum(differences * differences, axis=2)
        output[start : start + len(chunk)] = np.sqrt(np.min(squared, axis=1))
    return output


def boundary_metrics(
    ground_truth: np.ndarray | Image.Image,
    prediction: np.ndarray | Image.Image,
    *,
    tolerance_pixels: float = 2.0,
) -> BoundaryMetrics:
    if tolerance_pixels < 0:
        raise ValueError("Boundary tolerance cannot be negative")
    gt = _coordinates(boundary(ground_truth))
    pred = _coordinates(boundary(prediction))
    if len(gt) == 0 and len(pred) == 0:
        return BoundaryMetrics(1.0, 1.0, 1.0, 0.0, 0.0)
    if len(gt) == 0 or len(pred) == 0:
        return BoundaryMetrics(0.0, 0.0, 0.0, None, None)
    pred_to_gt = _directed_nearest_distances(pred, gt)
    gt_to_pred = _directed_nearest_distances(gt, pred)
    precision = float(np.mean(pred_to_gt <= tolerance_pixels))
    recall = float(np.mean(gt_to_pred <= tolerance_pixels))
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    hausdorff = float(max(np.max(pred_to_gt), np.max(gt_to_pred)))
    assd = float((np.mean(pred_to_gt) + np.mean(gt_to_pred)) / 2)
    return BoundaryMetrics(precision, recall, f1, hausdorff, assd)


def panoptic_metrics(
    matched_ious: Sequence[float],
    *,
    true_positive_count: int,
    false_positive_count: int,
    false_negative_count: int,
) -> PanopticMetrics:
    denominator = true_positive_count + 0.5 * false_positive_count + 0.5 * false_negative_count
    recognition = true_positive_count / denominator if denominator else 1.0
    segmentation = (
        sum(float(value) for value in matched_ious) / true_positive_count
        if true_positive_count
        else 0.0
    )
    return PanopticMetrics(
        panoptic_quality=segmentation * recognition,
        segmentation_quality=segmentation,
        recognition_quality=recognition,
    )


def area_stratum(
    area_pixels: int,
    *,
    small_max_pixels: int,
    large_min_pixels: int,
) -> str:
    if area_pixels <= small_max_pixels:
        return "small"
    if area_pixels >= large_min_pixels:
        return "large"
    return "medium"


def confidence_calibration(
    observations: Sequence[tuple[float, bool]],
    *,
    bin_count: int = 10,
) -> tuple[list[CalibrationBin], float]:
    if bin_count < 1:
        raise ValueError("Calibration bin count must be positive")
    bins: list[CalibrationBin] = []
    total = len(observations)
    weighted_gap = 0.0
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        selected = [
            (float(confidence), bool(matched))
            for confidence, matched in observations
            if lower <= confidence <= upper if index == bin_count - 1 else lower <= confidence < upper
        ]
        if selected:
            mean_confidence = sum(item[0] for item in selected) / len(selected)
            match_rate = sum(item[1] for item in selected) / len(selected)
            gap = abs(mean_confidence - match_rate)
            weighted_gap += gap * len(selected)
        else:
            mean_confidence = match_rate = gap = None
        bins.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(selected),
                mean_confidence=mean_confidence,
                empirical_match_rate=match_rate,
                calibration_gap=gap,
            )
        )
    return bins, weighted_gap / total if total else 0.0


def precision_recall_at_thresholds(
    predictions: Sequence[tuple[float, float]],
    *,
    ground_truth_count: int,
    confidence_thresholds: Sequence[float],
    match_iou_threshold: float,
) -> list[dict[str, float | int]]:
    """Summarize confidence sweeps from `(confidence, best_iou)` prediction rows."""

    output: list[dict[str, float | int]] = []
    for confidence_threshold in confidence_thresholds:
        selected = [row for row in predictions if row[0] >= confidence_threshold]
        true_positives = sum(row[1] >= match_iou_threshold for row in selected)
        false_positives = len(selected) - true_positives
        false_negatives = max(0, ground_truth_count - true_positives)
        precision = true_positives / len(selected) if selected else 0.0
        recall = true_positives / ground_truth_count if ground_truth_count else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        output.append(
            {
                "confidence_threshold": float(confidence_threshold),
                "true_positive_count": true_positives,
                "false_positive_count": false_positives,
                "false_negative_count": false_negatives,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )
    return output


def average_precision(
    ranked_predictions: Sequence[tuple[float, bool]],
    *,
    ground_truth_count: int,
) -> float:
    """Calculate interpolated all-points average precision from ranked matches."""

    if ground_truth_count <= 0:
        return 0.0
    rows = sorted(ranked_predictions, key=lambda item: item[0], reverse=True)
    cumulative_tp = 0
    cumulative_fp = 0
    recalls = [0.0]
    precisions = [1.0]
    for _, matched in rows:
        cumulative_tp += int(matched)
        cumulative_fp += int(not matched)
        recalls.append(cumulative_tp / ground_truth_count)
        precisions.append(cumulative_tp / max(cumulative_tp + cumulative_fp, 1))
    recalls.append(1.0)
    precisions.append(0.0)
    for index in range(len(precisions) - 2, -1, -1):
        precisions[index] = max(precisions[index], precisions[index + 1])
    return sum(
        (recalls[index] - recalls[index - 1]) * precisions[index]
        for index in range(1, len(recalls))
        if recalls[index] != recalls[index - 1]
    )
