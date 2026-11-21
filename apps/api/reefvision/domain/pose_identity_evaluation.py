"""Ground-truth identity metrics kept separate from landmark localization metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from reefvision.domain.pose_identity_tracking import minimum_cost_assignment


@dataclass(frozen=True)
class IdentityObservation:
    identity_id: str
    frame_index: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class PerIdentityMetrics:
    truth_identity_id: str
    predicted_identity_id: str | None
    truth_observations: int
    spatially_matched_observations: int
    identity_true_positives: int
    coverage: float
    identity_switches: int
    fragmentations: int


@dataclass(frozen=True)
class IdentityEvaluationReport:
    id_true_positives: int
    id_false_positives: int
    id_false_negatives: int
    id_precision: float
    id_recall: float
    id_f1: float
    identity_switches: int
    fragmentations: int
    spatial_matches: int
    spatial_misses: int
    spatial_false_positives: int
    association_successes: int
    association_failures: int
    identity_mapping: dict[str, str]
    per_identity: tuple[PerIdentityMetrics, ...]


def _iou(first: IdentityObservation, second: IdentityObservation) -> float:
    ax, ay, aw, ah = first.bbox
    bx, by, bw, bh = second.bbox
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def match_identity_frame(
    truth: list[IdentityObservation],
    predictions: list[IdentityObservation],
    threshold: float,
) -> list[tuple[IdentityObservation, IdentityObservation]]:
    ordered_truth = sorted(truth, key=lambda item: item.identity_id)
    ordered_predictions = sorted(predictions, key=lambda item: item.identity_id)
    if not ordered_truth or not ordered_predictions:
        return []
    real_columns = len(ordered_predictions)
    costs: list[list[float]] = []
    for truth_item in ordered_truth:
        row = []
        for prediction in ordered_predictions:
            overlap = _iou(truth_item, prediction)
            row.append(1.0 - overlap if overlap >= threshold else 1_000_000.0)
        row.extend(1.0 + index * 1e-9 for index in range(len(ordered_truth)))
        costs.append(row)
    matches = []
    for row_index, column in enumerate(minimum_cost_assignment(costs)):
        if column < real_columns and costs[row_index][column] < 1.0:
            matches.append((ordered_truth[row_index], ordered_predictions[column]))
    return matches


def _identity_mapping(
    truth_ids: list[str], predicted_ids: list[str], counts: Counter[tuple[str, str]]
) -> dict[str, str]:
    if not truth_ids or not predicted_ids:
        return {}
    max_count = max(counts.values(), default=0)
    real_columns = len(predicted_ids)
    costs = [
        [float(max_count - counts[(truth_id, prediction_id)]) for prediction_id in predicted_ids]
        + [float(max_count) + index * 1e-9 for index in range(len(truth_ids))]
        for truth_id in truth_ids
    ]
    mapping: dict[str, str] = {}
    for row, column in enumerate(minimum_cost_assignment(costs)):
        if column < real_columns and counts[(truth_ids[row], predicted_ids[column])] > 0:
            mapping[truth_ids[row]] = predicted_ids[column]
    return mapping


def evaluate_pose_identities(
    truth: list[IdentityObservation],
    predictions: list[IdentityObservation],
    *,
    iou_threshold: float = 0.5,
) -> IdentityEvaluationReport:
    if not truth:
        raise ValueError("Identity evaluation requires verified ground-truth observations")
    if not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold must be between zero and one")
    truth_keys = [(item.identity_id, item.frame_index) for item in truth]
    if len(truth_keys) != len(set(truth_keys)):
        raise ValueError("Ground truth must contain one observation per identity and frame")
    prediction_keys = [(item.identity_id, item.frame_index) for item in predictions]
    if len(prediction_keys) != len(set(prediction_keys)):
        raise ValueError("Predictions must contain one observation per identity and frame")

    truth_by_frame: dict[int, list[IdentityObservation]] = defaultdict(list)
    prediction_by_frame: dict[int, list[IdentityObservation]] = defaultdict(list)
    for item in truth:
        truth_by_frame[item.frame_index].append(item)
    for item in predictions:
        prediction_by_frame[item.frame_index].append(item)

    matched_by_truth: dict[tuple[str, int], str] = {}
    eligible_pair_counts: Counter[tuple[str, str]] = Counter()
    matched_prediction_keys: set[tuple[str, int]] = set()
    for frame in sorted(set(truth_by_frame) | set(prediction_by_frame)):
        for truth_item in truth_by_frame.get(frame, []):
            for prediction in prediction_by_frame.get(frame, []):
                if _iou(truth_item, prediction) >= iou_threshold:
                    eligible_pair_counts[(truth_item.identity_id, prediction.identity_id)] += 1
        for truth_item, prediction in match_identity_frame(
            truth_by_frame.get(frame, []),
            prediction_by_frame.get(frame, []),
            iou_threshold,
        ):
            matched_by_truth[(truth_item.identity_id, frame)] = prediction.identity_id
            matched_prediction_keys.add((prediction.identity_id, frame))

    truth_ids = sorted({item.identity_id for item in truth})
    predicted_ids = sorted({item.identity_id for item in predictions})
    mapping = _identity_mapping(truth_ids, predicted_ids, eligible_pair_counts)
    idtp = sum(
        eligible_pair_counts[(truth_id, prediction_id)]
        for truth_id, prediction_id in mapping.items()
    )
    idfn = len(truth) - idtp
    idfp = len(predictions) - idtp
    precision = idtp / (idtp + idfp) if idtp + idfp else 0.0
    recall = idtp / (idtp + idfn) if idtp + idfn else 0.0
    id_f1 = 2 * idtp / (2 * idtp + idfp + idfn) if 2 * idtp + idfp + idfn else 0.0

    per_identity: list[PerIdentityMetrics] = []
    total_switches = 0
    total_fragmentations = 0
    for truth_id in truth_ids:
        observations = sorted(
            (item for item in truth if item.identity_id == truth_id),
            key=lambda item: item.frame_index,
        )
        matched_ids = [
            matched_by_truth.get((truth_id, observation.frame_index))
            for observation in observations
        ]
        switches = 0
        previous_prediction: str | None = None
        for prediction_id in matched_ids:
            if prediction_id is None:
                continue
            if previous_prediction is not None and prediction_id != previous_prediction:
                switches += 1
            previous_prediction = prediction_id
        segments = 0
        previously_matched = False
        for prediction_id in matched_ids:
            is_matched = prediction_id is not None
            if is_matched and not previously_matched:
                segments += 1
            previously_matched = is_matched
        fragmentations = max(0, segments - 1)
        spatial_count = sum(item is not None for item in matched_ids)
        predicted_identity = mapping.get(truth_id)
        identity_matches = (
            eligible_pair_counts[(truth_id, predicted_identity)] if predicted_identity else 0
        )
        total_switches += switches
        total_fragmentations += fragmentations
        per_identity.append(
            PerIdentityMetrics(
                truth_identity_id=truth_id,
                predicted_identity_id=predicted_identity,
                truth_observations=len(observations),
                spatially_matched_observations=spatial_count,
                identity_true_positives=identity_matches,
                coverage=spatial_count / len(observations),
                identity_switches=switches,
                fragmentations=fragmentations,
            )
        )

    spatial_matches = len(matched_by_truth)
    spatial_identity_matches = sum(
        prediction_id == mapping.get(truth_id)
        for (truth_id, _frame), prediction_id in matched_by_truth.items()
    )
    return IdentityEvaluationReport(
        id_true_positives=idtp,
        id_false_positives=idfp,
        id_false_negatives=idfn,
        id_precision=precision,
        id_recall=recall,
        id_f1=id_f1,
        identity_switches=total_switches,
        fragmentations=total_fragmentations,
        spatial_matches=spatial_matches,
        spatial_misses=len(truth) - spatial_matches,
        spatial_false_positives=len(predictions) - len(matched_prediction_keys),
        association_successes=spatial_identity_matches,
        association_failures=spatial_matches - spatial_identity_matches,
        identity_mapping=mapping,
        per_identity=tuple(per_identity),
    )
