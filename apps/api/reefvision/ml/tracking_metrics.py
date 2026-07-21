"""Tracker-independent multi-object tracking and behavior evaluation metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TrackBox:
    frame_index: int
    track_id: str
    x: float
    y: float
    width: float
    height: float
    confidence: float | None = None
    depth: float | None = None


@dataclass(frozen=True)
class FrameMatch:
    frame_index: int
    reference_track_id: str
    predicted_track_id: str
    iou: float
    center_error: float
    depth_error: float | None


@dataclass(frozen=True)
class TrackingFrameSummary:
    frame_index: int
    reference_count: int
    predicted_count: int
    matched_count: int
    false_positive_count: int
    false_negative_count: int
    identity_switch_count: int
    mean_iou: float | None


@dataclass(frozen=True)
class TrackingTrackSummary:
    reference_track_id: str
    reference_observation_count: int
    matched_observation_count: int
    coverage: float
    fragmentation_count: int
    identity_switch_count: int
    matched_prediction_track_ids: tuple[str, ...]
    mostly_tracked: bool
    mostly_lost: bool


@dataclass(frozen=True)
class TrackingMetrics:
    reference_detection_count: int
    predicted_detection_count: int
    matched_detection_count: int
    false_positive_count: int
    false_negative_count: int
    false_positive_track_count: int
    false_negative_track_count: int
    identity_switch_count: int
    fragmentation_count: int
    mostly_tracked_count: int
    mostly_lost_count: int
    mota: float
    motp: float
    localization_iou: float
    detection_precision: float
    detection_recall: float
    id_precision: float
    id_recall: float
    idf1: float
    detection_accuracy: float
    association_accuracy: float
    hota: float
    mean_center_error: float | None
    mean_depth_error: float | None
    mean_track_lifespan_frames: float | None
    mean_track_continuity: float | None
    matches: tuple[FrameMatch, ...]
    per_frame: tuple[TrackingFrameSummary, ...]
    per_track: tuple[TrackingTrackSummary, ...]


def box_iou(first: TrackBox, second: TrackBox) -> float:
    first_x2 = first.x + first.width
    first_y2 = first.y + first.height
    second_x2 = second.x + second.width
    second_y2 = second.y + second.height
    intersection_width = max(0.0, min(first_x2, second_x2) - max(first.x, second.x))
    intersection_height = max(0.0, min(first_y2, second_y2) - max(first.y, second.y))
    intersection = intersection_width * intersection_height
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union > 0 else 0.0


def center_distance(first: TrackBox, second: TrackBox) -> float:
    return math.hypot(
        first.x + first.width / 2 - second.x - second.width / 2,
        first.y + first.height / 2 - second.y - second.height / 2,
    )


def _frame_matches(
    references: Sequence[TrackBox],
    predictions: Sequence[TrackBox],
    *,
    minimum_iou: float,
    maximum_depth_gap: float | None,
) -> tuple[list[FrameMatch], set[int], set[int]]:
    candidates: list[tuple[float, float, int, int]] = []
    for reference_index, reference in enumerate(references):
        for prediction_index, prediction in enumerate(predictions):
            iou = box_iou(reference, prediction)
            if iou < minimum_iou:
                continue
            depth_gap = None
            if reference.depth is not None and prediction.depth is not None:
                depth_gap = abs(reference.depth - prediction.depth)
                if maximum_depth_gap is not None and depth_gap > maximum_depth_gap:
                    continue
            candidates.append(
                (
                    iou,
                    -center_distance(reference, prediction),
                    reference_index,
                    prediction_index,
                )
            )
    used_references: set[int] = set()
    used_predictions: set[int] = set()
    matches: list[FrameMatch] = []
    for iou, _negative_center_error, reference_index, prediction_index in sorted(
        candidates,
        reverse=True,
    ):
        if reference_index in used_references or prediction_index in used_predictions:
            continue
        used_references.add(reference_index)
        used_predictions.add(prediction_index)
        reference = references[reference_index]
        prediction = predictions[prediction_index]
        depth_error = (
            abs(reference.depth - prediction.depth)
            if reference.depth is not None and prediction.depth is not None
            else None
        )
        matches.append(
            FrameMatch(
                frame_index=reference.frame_index,
                reference_track_id=reference.track_id,
                predicted_track_id=prediction.track_id,
                iou=iou,
                center_error=center_distance(reference, prediction),
                depth_error=depth_error,
            )
        )
    return matches, used_references, used_predictions


def evaluate_tracking(
    references: Sequence[TrackBox],
    predictions: Sequence[TrackBox],
    *,
    minimum_iou: float = 0.5,
    maximum_depth_gap: float | None = None,
    mostly_tracked_threshold: float = 0.8,
    mostly_lost_threshold: float = 0.2,
) -> TrackingMetrics:
    if not 0 <= minimum_iou <= 1:
        raise ValueError("minimum_iou must lie between zero and one")
    reference_by_frame: dict[int, list[TrackBox]] = defaultdict(list)
    prediction_by_frame: dict[int, list[TrackBox]] = defaultdict(list)
    for box in references:
        reference_by_frame[box.frame_index].append(box)
    for box in predictions:
        prediction_by_frame[box.frame_index].append(box)

    matches: list[FrameMatch] = []
    false_positives = 0
    false_negatives = 0
    frame_summaries: list[TrackingFrameSummary] = []
    for frame_index in sorted(set(reference_by_frame) | set(prediction_by_frame)):
        frame_matches, used_references, used_predictions = _frame_matches(
            reference_by_frame[frame_index],
            prediction_by_frame[frame_index],
            minimum_iou=minimum_iou,
            maximum_depth_gap=maximum_depth_gap,
        )
        matches.extend(frame_matches)
        frame_false_negatives = len(reference_by_frame[frame_index]) - len(used_references)
        frame_false_positives = len(prediction_by_frame[frame_index]) - len(used_predictions)
        false_negatives += frame_false_negatives
        false_positives += frame_false_positives
        frame_summaries.append(
            TrackingFrameSummary(
                frame_index=frame_index,
                reference_count=len(reference_by_frame[frame_index]),
                predicted_count=len(prediction_by_frame[frame_index]),
                matched_count=len(frame_matches),
                false_positive_count=frame_false_positives,
                false_negative_count=frame_false_negatives,
                identity_switch_count=0,
                mean_iou=(
                    sum(match.iou for match in frame_matches) / len(frame_matches)
                    if frame_matches
                    else None
                ),
            )
        )

    matches_by_reference: dict[str, list[FrameMatch]] = defaultdict(list)
    for match in matches:
        matches_by_reference[match.reference_track_id].append(match)
    identity_switches = 0
    fragmentations = 0
    reference_frames: dict[str, set[int]] = defaultdict(set)
    for box in references:
        reference_frames[box.track_id].add(box.frame_index)
    track_ratios: dict[str, float] = {}
    continuity_scores: list[float] = []
    lifespans: list[float] = []
    association_correct = 0
    association_total = 0
    per_track: list[TrackingTrackSummary] = []
    switch_counts_by_frame: defaultdict[int, int] = defaultdict(int)
    for track_id, frames in reference_frames.items():
        ordered_matches = sorted(
            matches_by_reference.get(track_id, []),
            key=lambda item: item.frame_index,
        )
        track_ratios[track_id] = len(ordered_matches) / len(frames) if frames else 0.0
        lifespans.append(float(max(frames) - min(frames) + 1))
        previous_prediction = None
        matched_by_frame = {match.frame_index: match for match in ordered_matches}
        active_segments = 0
        in_segment = False
        track_switches = 0
        for match in ordered_matches:
            if previous_prediction is not None:
                association_total += 1
                if match.predicted_track_id == previous_prediction:
                    association_correct += 1
                else:
                    identity_switches += 1
                    track_switches += 1
                    switch_counts_by_frame[match.frame_index] += 1
            previous_prediction = match.predicted_track_id
        segment_lengths: list[int] = []
        segment_length = 0
        for frame_index in sorted(frames):
            if frame_index in matched_by_frame:
                if not in_segment:
                    active_segments += 1
                    in_segment = True
                segment_length += 1
            elif in_segment:
                segment_lengths.append(segment_length)
                segment_length = 0
                in_segment = False
        if in_segment:
            segment_lengths.append(segment_length)
        fragmentations += max(0, active_segments - 1)
        continuity_scores.append(max(segment_lengths, default=0) / len(frames) if frames else 0.0)
        coverage = track_ratios[track_id]
        per_track.append(
            TrackingTrackSummary(
                reference_track_id=track_id,
                reference_observation_count=len(frames),
                matched_observation_count=len(ordered_matches),
                coverage=coverage,
                fragmentation_count=max(0, active_segments - 1),
                identity_switch_count=track_switches,
                matched_prediction_track_ids=tuple(
                    sorted({match.predicted_track_id for match in ordered_matches})
                ),
                mostly_tracked=coverage >= mostly_tracked_threshold,
                mostly_lost=coverage <= mostly_lost_threshold,
            )
        )

    frame_summaries = [
        TrackingFrameSummary(
            frame_index=item.frame_index,
            reference_count=item.reference_count,
            predicted_count=item.predicted_count,
            matched_count=item.matched_count,
            false_positive_count=item.false_positive_count,
            false_negative_count=item.false_negative_count,
            identity_switch_count=switch_counts_by_frame[item.frame_index],
            mean_iou=item.mean_iou,
        )
        for item in frame_summaries
    ]

    reference_count = len(references)
    predicted_count = len(predictions)
    matched_count = len(matches)
    mota = (
        1 - (false_negatives + false_positives + identity_switches) / reference_count
        if reference_count
        else 0.0
    )
    motp = sum(match.iou for match in matches) / matched_count if matched_count else 0.0
    detection_precision = matched_count / predicted_count if predicted_count else 0.0
    detection_recall = matched_count / reference_count if reference_count else 0.0
    id_precision = detection_precision
    id_recall = detection_recall
    idf1 = (
        2 * id_precision * id_recall / (id_precision + id_recall)
        if id_precision + id_recall
        else 0.0
    )
    detection_accuracy = (
        matched_count / (matched_count + false_positives + false_negatives)
        if matched_count + false_positives + false_negatives
        else 1.0
    )
    association_accuracy = association_correct / association_total if association_total else 1.0
    hota = math.sqrt(max(detection_accuracy * association_accuracy, 0.0))
    depth_errors = [match.depth_error for match in matches if match.depth_error is not None]
    matched_reference_ids = {match.reference_track_id for match in matches}
    matched_prediction_ids = {match.predicted_track_id for match in matches}
    all_prediction_ids = {box.track_id for box in predictions}
    return TrackingMetrics(
        reference_detection_count=reference_count,
        predicted_detection_count=predicted_count,
        matched_detection_count=matched_count,
        false_positive_count=false_positives,
        false_negative_count=false_negatives,
        false_positive_track_count=len(all_prediction_ids - matched_prediction_ids),
        false_negative_track_count=len(set(reference_frames) - matched_reference_ids),
        identity_switch_count=identity_switches,
        fragmentation_count=fragmentations,
        mostly_tracked_count=sum(
            ratio >= mostly_tracked_threshold for ratio in track_ratios.values()
        ),
        mostly_lost_count=sum(ratio <= mostly_lost_threshold for ratio in track_ratios.values()),
        mota=mota,
        motp=motp,
        localization_iou=motp,
        detection_precision=detection_precision,
        detection_recall=detection_recall,
        id_precision=id_precision,
        id_recall=id_recall,
        idf1=idf1,
        detection_accuracy=detection_accuracy,
        association_accuracy=association_accuracy,
        hota=hota,
        mean_center_error=(
            sum(match.center_error for match in matches) / matched_count if matched_count else None
        ),
        mean_depth_error=(sum(depth_errors) / len(depth_errors) if depth_errors else None),
        mean_track_lifespan_frames=(sum(lifespans) / len(lifespans) if lifespans else None),
        mean_track_continuity=(
            sum(continuity_scores) / len(continuity_scores) if continuity_scores else None
        ),
        matches=tuple(
            sorted(matches, key=lambda item: (item.frame_index, item.reference_track_id))
        ),
        per_frame=tuple(frame_summaries),
        per_track=tuple(sorted(per_track, key=lambda item: item.reference_track_id)),
    )
