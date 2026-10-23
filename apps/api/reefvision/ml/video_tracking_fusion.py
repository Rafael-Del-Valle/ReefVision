"""Class-aware fusion of independently tracked detector and segmenter results.

BoT-SORT/ByteTrack link each model independently. Fusion reconciles track
identities using overlapping same-frame predictions, never inventing a mask.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from math import isclose

from reefvision.ml.video_tracking import TrackObservation


@dataclass(frozen=True)
class HybridFusionReport:
    matched_track_pairs: int
    detector_observations: int
    segmenter_observations: int
    fused_observations: int
    masked_observations: int


def box_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def fuse_tracked_models(
    detections: list[TrackObservation],
    segmentations: list[TrackObservation],
    *,
    detector_class_map: dict[str, str],
    segmenter_class_map: dict[str, str],
    minimum_iou: float = 0.5,
) -> tuple[list[TrackObservation], HybridFusionReport]:
    """Reconcile model-native IDs without conflating incompatible project labels.

    Track-level matching is a deterministic one-to-one assignment based on the
    number of distinct overlapping frames, then cumulative IoU. Same-frame
    segmentation augments detector geometry; segmentation fills detector gaps
    only when its identity has been matched. Unmatched segmentation tracks
    receive separate noncolliding IDs.
    """
    if not 0 < minimum_iou <= 1:
        raise ValueError("Hybrid overlap threshold must be greater than zero and at most one")

    detector_frames: dict[int, list[TrackObservation]] = defaultdict(list)
    segmenter_frames: dict[int, list[TrackObservation]] = defaultdict(list)
    for observation in detections:
        detector_frames[observation.frame].append(observation)
    for observation in segmentations:
        segmenter_frames[observation.frame].append(observation)

    evidence: dict[tuple[int, int], list[float]] = defaultdict(list)
    for frame, segment_items in segmenter_frames.items():
        proposals: list[tuple[float, int, int]] = []
        for detector in detector_frames.get(frame, []):
            detector_label = detector_class_map.get(detector.class_name.strip().casefold())
            if detector_label is None:
                continue
            for segmenter in segment_items:
                if detector_label != segmenter_class_map.get(
                    segmenter.class_name.strip().casefold()
                ):
                    continue
                overlap = box_iou(detector.bbox, segmenter.bbox)
                if overlap >= minimum_iou:
                    proposals.append(
                        (overlap, detector.provider_track_id, segmenter.provider_track_id)
                    )
        detector_candidates: dict[int, list[tuple[float, int]]] = defaultdict(list)
        segmenter_candidates: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for overlap, detection_id, segmentation_id in proposals:
            detector_candidates[detection_id].append((overlap, segmentation_id))
            segmenter_candidates[segmentation_id].append((overlap, detection_id))

        def unique_best(candidates: list[tuple[float, int]]) -> int | None:
            maximum = max((candidate[0] for candidate in candidates), default=None)
            if maximum is None:
                return None
            winners = [
                identity
                for overlap, identity in candidates
                if isclose(overlap, maximum, rel_tol=1e-12, abs_tol=1e-12)
            ]
            return winners[0] if len(winners) == 1 else None

        detector_best = {
            identity: unique_best(candidates)
            for identity, candidates in detector_candidates.items()
        }
        segmenter_best = {
            identity: unique_best(candidates)
            for identity, candidates in segmenter_candidates.items()
        }
        used_detector: set[int] = set()
        used_segmenter: set[int] = set()
        for overlap, detection_id, segmentation_id in sorted(
            proposals, key=lambda candidate: (-candidate[0], candidate[1], candidate[2])
        ):
            # Crossing objects can yield equally plausible same-frame matches.
            # Only use mutual, unique best overlaps as identity evidence rather
            # than resolving scientific ambiguity with an arbitrary ID order.
            if (
                detector_best[detection_id] != segmentation_id
                or segmenter_best[segmentation_id] != detection_id
            ):
                continue
            if detection_id in used_detector or segmentation_id in used_segmenter:
                continue
            used_detector.add(detection_id)
            used_segmenter.add(segmentation_id)
            evidence[(detection_id, segmentation_id)].append(overlap)

    linked_segments: dict[int, int] = {}
    linked_detectors: set[int] = set()
    proposals_by_track = sorted(
        evidence.items(),
        key=lambda item: (-len(item[1]), -sum(item[1]), item[0]),
    )
    for (detection_id, segmentation_id), overlaps in proposals_by_track:
        if not overlaps or detection_id in linked_detectors or segmentation_id in linked_segments:
            continue
        linked_detectors.add(detection_id)
        linked_segments[segmentation_id] = detection_id

    fused: dict[tuple[int, int], TrackObservation] = {
        (item.frame, item.provider_track_id): item for item in detections
    }
    reserved_ids = {item.provider_track_id for item in detections}
    next_id = max(reserved_ids, default=0) + 1
    unmatched_id_map: dict[int, int] = {}

    for item in sorted(segmentations, key=lambda value: (value.frame, value.provider_track_id)):
        class_id = segmenter_class_map.get(item.class_name.strip().casefold())
        if class_id is None:
            continue
        if item.provider_track_id in linked_segments:
            track_id = linked_segments[item.provider_track_id]
        else:
            if item.provider_track_id not in unmatched_id_map:
                while next_id in reserved_ids:
                    next_id += 1
                unmatched_id_map[item.provider_track_id] = next_id
                reserved_ids.add(next_id)
                next_id += 1
            track_id = unmatched_id_map[item.provider_track_id]

        key = (item.frame, track_id)
        existing = fused.get(key)
        if existing is not None:
            # Preserve detection identity and box unless the segmentation
            # observation actually overlaps that detector on this frame.
            if (
                detector_class_map.get(existing.class_name.strip().casefold()) == class_id
                and box_iou(existing.bbox, item.bbox) >= minimum_iou
                and item.mask_polygons
            ):
                fused[key] = replace(existing, mask_polygons=item.mask_polygons)
            continue
        fused[key] = replace(
            item,
            provider_track_id=track_id,
            class_name=f"project:{class_id}",
        )

    output = sorted(fused.values(), key=lambda item: (item.frame, item.provider_track_id))
    return output, HybridFusionReport(
        matched_track_pairs=len(linked_segments),
        detector_observations=len(detections),
        segmenter_observations=len(segmentations),
        fused_observations=len(output),
        masked_observations=sum(bool(item.mask_polygons) for item in output),
    )
