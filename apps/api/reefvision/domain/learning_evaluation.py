"""Deterministic source-pixel detection metrics; no model framework required."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoredBox:
    image_id: str
    class_id: str
    score: float
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class ClassDetectionMetrics:
    ground_truth_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    ap50: float


@dataclass(frozen=True)
class DetectionMetrics:
    map50: float
    precision: float
    recall: float
    count_bias_per_image: float
    mean_absolute_count_error: float
    per_class: dict[str, ClassDetectionMetrics]


def box_iou(a: ScoredBox, b: ScoredBox) -> float:
    ax, ay, bx, by = a.bounds
    cx, cy, dx, dy = b.bounds
    intersection = max(0.0, min(bx, dx) - max(ax, cx)) * max(0.0, min(by, dy) - max(ay, cy))
    union = (bx - ax) * (by - ay) + (dx - cx) * (dy - cy) - intersection
    return intersection / union if union > 0 else 0.0


def detection_metrics(
    truth: list[ScoredBox],
    predictions: list[ScoredBox],
    *,
    image_count: int,
    operating_confidence: float = 0.25,
) -> DetectionMetrics:
    """AP50 uses all scores; precision/count errors use the fixed operating point.

    Greedy confidence-ordered, same-class, same-image one-to-one IoU>=0.5 matching.
    AP is the all-points precision envelope integral, not COCO's sampled mAP50:95.
    """
    metrics: dict[str, ClassDetectionMetrics] = {}
    total_tp = total_fp = total_fn = 0
    for class_id in sorted({item.class_id for item in truth + predictions}):
        actual = [item for item in truth if item.class_id == class_id]
        proposed = sorted(
            (item for item in predictions if item.class_id == class_id),
            key=lambda item: (-item.score, item.image_id, item.bounds),
        )
        matched: set[int] = set()
        true_positives = false_positives = running_tp = 0
        curve: list[tuple[float, float]] = []
        for rank, item in enumerate(proposed, 1):
            options = [
                (box_iou(item, label), index)
                for index, label in enumerate(actual)
                if index not in matched and label.image_id == item.image_id
            ]
            overlap, match = max(options, default=(0.0, -1))
            hit = overlap >= 0.5
            if hit:
                matched.add(match)
                running_tp += 1
            if item.score >= operating_confidence:
                true_positives += int(hit)
                false_positives += int(not hit)
            curve.append((running_tp / len(actual) if actual else 0.0, running_tp / rank))
        envelope = 0.0
        reversed_curve: list[tuple[float, float]] = []
        for recall, precision in reversed(curve):
            envelope = max(envelope, precision)
            reversed_curve.append((recall, envelope))
        ap = previous_recall = 0.0
        for recall, precision in reversed(reversed_curve):
            ap += (recall - previous_recall) * precision
            previous_recall = recall
        false_negatives = len(actual) - true_positives
        total_tp += true_positives
        total_fp += false_positives
        total_fn += false_negatives
        metrics[class_id] = ClassDetectionMetrics(
            len(actual),
            true_positives,
            false_positives,
            false_negatives,
            true_positives / max(true_positives + false_positives, 1),
            true_positives / max(len(actual), 1),
            ap,
        )
    counted = [item for item in predictions if item.score >= operating_confidence]
    images = {item.image_id for item in truth + predictions}
    absolute_error = sum(
        abs(
            sum(item.image_id == image for item in counted)
            - sum(item.image_id == image for item in truth)
        )
        for image in images
    )
    supported = [item.ap50 for item in metrics.values() if item.ground_truth_count]
    return DetectionMetrics(
        map50=sum(supported) / max(len(supported), 1),
        precision=total_tp / max(total_tp + total_fp, 1),
        recall=total_tp / max(total_tp + total_fn, 1),
        count_bias_per_image=(len(counted) - len(truth)) / max(image_count, 1),
        mean_absolute_count_error=absolute_error / max(image_count, 1),
        per_class=metrics,
    )
