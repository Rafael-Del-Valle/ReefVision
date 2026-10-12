"""Immutable source-pixel instance-mask IoU and AP50 metrics.

Masks use sorted, half-open row-runs (row, start_x, end_x). This represents
holes and disconnected components without flattening raster geometry.
This module does NOT implement candidate promotion or deployment.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ScoredInstanceMask:
    image_id: str
    class_id: str
    score: float
    width: int
    height: int
    runs: tuple[tuple[int, int, int], ...]

    def __post_init__(self) -> None:
        if not self.image_id or not self.class_id:
            raise ValueError("Mask needs an image and class")
        if not isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError("Mask confidence must be finite and within [0,1]")
        if self.width <= 0 or self.height <= 0 or not self.runs:
            raise ValueError("Mask needs positive image dimensions and nonempty pixels")
        last: tuple[int, int, int] | None = None
        for row, start, end in self.runs:
            if not (0 <= row < self.height and 0 <= start < end <= self.width):
                raise ValueError("Mask pixel run out of source-image bounds")
            if last and (row < last[0] or (row == last[0] and start < last[2])):
                raise ValueError("Mask runs must be row sorted and nonoverlapping")
            last = (row, start, end)


@dataclass(frozen=True)
class ClassMaskMetrics:
    ground_truth_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    ap50: float


@dataclass(frozen=True)
class InstanceMaskMetrics:
    mask_map50: float
    precision: float
    recall: float
    count_bias_per_image: float
    mean_absolute_count_error: float
    mean_matched_mask_iou: float
    per_class: dict[str, ClassMaskMetrics]


def mask_iou(a: ScoredInstanceMask, b: ScoredInstanceMask) -> float:
    """Exact binary IoU for run-length masks; no bounding-box approximation."""
    if a.image_id != b.image_id:
        return 0.0
    if (a.width, a.height) != (b.width, b.height):
        raise ValueError("Masks of one image must have the same source dimensions")
    a_area = sum(end - start for _, start, end in a.runs)
    b_area = sum(end - start for _, start, end in b.runs)
    overlap = 0
    i = j = 0
    while i < len(a.runs) and j < len(b.runs):
        ar, ax0, ax1 = a.runs[i]
        br, bx0, bx1 = b.runs[j]
        if ar < br:
            i += 1
        elif br < ar:
            j += 1
        else:
            overlap += max(0, min(ax1, bx1) - max(ax0, bx0))
            if ax1 <= bx1:
                i += 1
            if bx1 <= ax1:
                j += 1
    return overlap / (a_area + b_area - overlap)


def _average_precision(curve: list[tuple[float, float]]) -> float:
    envelope = 0.0
    reverse: list[tuple[float, float]] = []
    for recall, precision in reversed(curve):
        envelope = max(envelope, precision)
        reverse.append((recall, envelope))
    ap = previous = 0.0
    for recall, precision in reversed(reverse):
        ap += (recall - previous) * precision
        previous = recall
    return ap


def instance_mask_metrics(
    truth: list[ScoredInstanceMask],
    predictions: list[ScoredInstanceMask],
    *,
    image_count: int,
    operating_confidence: float = 0.25,
    iou_threshold: float = 0.5,
) -> InstanceMaskMetrics:
    """One-to-one, same-image/class AP50 with operating-point precision/counts.

    AP50 uses all confidence scores and mask IoU>=0.5 by default. This is NOT
    COCO mask mAP50:95 or an evaluation/promotion eligibility determination.
    """
    if image_count < 1 or not 0 <= operating_confidence <= 1 or not 0 < iou_threshold <= 1:
        raise ValueError("Invalid held-out image count or metric threshold")
    dims: dict[str, tuple[int, int]] = {}
    for mask in [*truth, *predictions]:
        size = (mask.width, mask.height)
        if mask.image_id in dims and dims[mask.image_id] != size:
            raise ValueError("Inconsistent dimensions for the same image")
        dims[mask.image_id] = size
    if len(dims) > image_count:
        raise ValueError("Mask image IDs exceed the held-out image count")

    per_class: dict[str, ClassMaskMetrics] = {}
    total_tp = total_fp = total_fn = 0
    matched_ious: list[float] = []
    for class_id in sorted({x.class_id for x in [*truth, *predictions]}):
        actual = [x for x in truth if x.class_id == class_id]
        ranked = sorted(
            (x for x in predictions if x.class_id == class_id),
            key=lambda x: (-x.score, x.image_id, x.runs),
        )
        matched: set[int] = set()
        running_tp = tp = fp = 0
        curve: list[tuple[float, float]] = []
        for rank, proposal in enumerate(ranked, start=1):
            options = [
                (mask_iou(proposal, item), k)
                for k, item in enumerate(actual)
                if k not in matched and item.image_id == proposal.image_id
            ]
            iou, match = max(options, default=(0.0, -1))
            hit = iou >= iou_threshold
            if hit:
                matched.add(match)
                running_tp += 1
            if proposal.score >= operating_confidence:
                tp += int(hit)
                fp += int(not hit)
                if hit:
                    matched_ious.append(iou)
            curve.append((running_tp / len(actual) if actual else 0.0, running_tp / rank))
        fn = len(actual) - tp
        total_tp += tp
        total_fp += fp
        total_fn += fn
        per_class[class_id] = ClassMaskMetrics(
            len(actual), tp, fp, fn,
            tp / max(tp + fp, 1),
            tp / max(len(actual), 1),
            _average_precision(curve),
        )

    counted = [p for p in predictions if p.score >= operating_confidence]
    absolute_error = sum(
        abs(
            sum(p.image_id == image_id for p in counted)
            - sum(t.image_id == image_id for t in truth)
        )
        for image_id in dims
    )
    supported = [v.ap50 for v in per_class.values() if v.ground_truth_count]
    return InstanceMaskMetrics(
        mask_map50=sum(supported) / max(len(supported), 1),
        precision=total_tp / max(total_tp + total_fp, 1),
        recall=total_tp / max(total_tp + total_fn, 1),
        count_bias_per_image=(len(counted) - len(truth)) / image_count,
        mean_absolute_count_error=absolute_error / image_count,
        mean_matched_mask_iou=sum(matched_ious) / max(len(matched_ious), 1),
        per_class=per_class,
    )
