"""Deterministic multi-source detection consensus for executable workflows."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256


@dataclass(frozen=True, slots=True)
class _Detection:
    source_id: str
    source_kind: str
    proposal_id: str | None
    image_id: str
    label_class_id: str | None
    predicted_label: str
    confidence: float
    box: tuple[float, float, float, float]
    provenance: dict[str, Any]

    @property
    def class_key(self) -> str:
        return self.label_class_id or self.predicted_label


@dataclass(slots=True)
class _Cluster:
    image_id: str
    class_key: str
    members: list[_Detection] = field(default_factory=list)
    representative_box: tuple[float, float, float, float] | None = None
    box_fallback: bool = False

    @property
    def source_ids(self) -> set[str]:
        return {member.source_id for member in self.members}


def _box_from_detection(raw: dict[str, Any]) -> tuple[float, float, float, float]:
    raw_box = raw.get("box")
    box: dict[str, Any] = raw_box if isinstance(raw_box, dict) else raw
    try:
        x_min = float(box["x_min"])
        y_min = float(box["y_min"])
        x_max = float(box["x_max"])
        y_max = float(box["y_max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Detection consensus requires x_min/y_min/x_max/y_max boxes") from exc
    if x_max <= x_min or y_max <= y_min:
        raise ValidationError("Detection consensus received an invalid bounding box")
    return x_min, y_min, x_max, y_max


def _iou(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    inter_x_min = max(left[0], right[0])
    inter_y_min = max(left[1], right[1])
    inter_x_max = min(left[2], right[2])
    inter_y_max = min(left[3], right[3])
    inter_width = max(0.0, inter_x_max - inter_x_min)
    inter_height = max(0.0, inter_y_max - inter_y_min)
    intersection = inter_width * inter_height
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _aggregate_box(
    members: list[_Detection],
    strategy: str,
) -> tuple[tuple[float, float, float, float], bool]:
    boxes = [member.box for member in members]
    if strategy == "mean":
        mean_box = (
            sum(box[0] for box in boxes) / len(boxes),
            sum(box[1] for box in boxes) / len(boxes),
            sum(box[2] for box in boxes) / len(boxes),
            sum(box[3] for box in boxes) / len(boxes),
        )
        return (
            mean_box,
            False,
        )
    if strategy == "union":
        return (
            (
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ),
            False,
        )
    if strategy == "intersection":
        intersection = (
            max(box[0] for box in boxes),
            max(box[1] for box in boxes),
            min(box[2] for box in boxes),
            min(box[3] for box in boxes),
        )
        if intersection[2] > intersection[0] and intersection[3] > intersection[1]:
            return intersection, False
        mean_box = (
            sum(box[0] for box in boxes) / len(boxes),
            sum(box[1] for box in boxes) / len(boxes),
            sum(box[2] for box in boxes) / len(boxes),
            sum(box[3] for box in boxes) / len(boxes),
        )
        return mean_box, True
    raise ValidationError("Consensus box_strategy must be mean, intersection, or union")


def _normalize_sources(
    sources: list[dict[str, Any]],
    confidence_threshold: float,
) -> tuple[list[_Detection], list[str]]:
    normalized: list[_Detection] = []
    source_ids: list[str] = []
    for source_index, payload in enumerate(sources, start=1):
        source_id = str(
            payload.get("source_id")
            or payload.get("source_model_id")
            or payload.get("model_id")
            or f"source-{source_index}"
        )
        if source_id in source_ids:
            raise ValidationError("Detection consensus requires unique prediction sources")
        source_ids.append(source_id)
        source_kind = str(payload.get("source_kind") or payload.get("provider_name") or "model")
        raw_detections = payload.get("detections", [])
        if not isinstance(raw_detections, list):
            raise ValidationError("Detection consensus source detections must be a list")
        for raw in raw_detections:
            if not isinstance(raw, dict):
                raise ValidationError("Detection consensus entries must be objects")
            confidence = float(raw.get("confidence", 0.0))
            if confidence < confidence_threshold:
                continue
            image_id = str(raw.get("image_id") or "")
            predicted_label = str(raw.get("predicted_label") or raw.get("label") or "")
            label_class_id = raw.get("label_class_id")
            label_class_id = str(label_class_id) if label_class_id is not None else None
            if not image_id or not (label_class_id or predicted_label):
                raise ValidationError(
                    "Detection consensus requires image_id and a class ID or predicted label"
                )
            normalized.append(
                _Detection(
                    source_id=source_id,
                    source_kind=source_kind,
                    proposal_id=(
                        str(raw["proposal_id"]) if raw.get("proposal_id") is not None else None
                    ),
                    image_id=image_id,
                    label_class_id=label_class_id,
                    predicted_label=predicted_label or str(label_class_id),
                    confidence=confidence,
                    box=_box_from_detection(raw),
                    provenance=dict(raw.get("provenance") or {}),
                )
            )
    return normalized, source_ids


def build_detection_consensus(
    sources: list[dict[str, Any]],
    *,
    required_votes: int = 2,
    iou_threshold: float = 0.5,
    confidence_threshold: float = 0.0,
    class_aware: bool = True,
    box_strategy: str = "mean",
) -> dict[str, Any]:
    """Return accepted and disagreement clusters with one vote maximum per source."""

    if not sources:
        raise ValidationError("Detection consensus requires at least one prediction source")
    if required_votes < 1:
        raise ValidationError("required_votes must be at least 1")
    if not 0.0 <= iou_threshold <= 1.0:
        raise ValidationError("iou_threshold must be between 0 and 1")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValidationError("confidence_threshold must be between 0 and 1")
    if box_strategy not in {"mean", "intersection", "union"}:
        raise ValidationError("Consensus box_strategy must be mean, intersection, or union")

    detections, source_ids = _normalize_sources(sources, confidence_threshold)
    if required_votes > len(source_ids):
        raise ValidationError("required_votes cannot exceed the number of prediction sources")

    grouped: dict[tuple[str, str], list[_Detection]] = defaultdict(list)
    for detection in detections:
        group_key = detection.class_key if class_aware else "*"
        grouped[(detection.image_id, group_key)].append(detection)

    clusters: list[_Cluster] = []
    for (image_id, class_key), group in sorted(grouped.items()):
        group.sort(
            key=lambda item: (
                -item.confidence,
                item.source_id,
                item.proposal_id or "",
                item.box,
            )
        )
        local_clusters: list[_Cluster] = []
        for detection in group:
            candidates: list[tuple[float, int, _Cluster]] = []
            for index, cluster in enumerate(local_clusters):
                if detection.source_id in cluster.source_ids or cluster.representative_box is None:
                    continue
                overlap = _iou(detection.box, cluster.representative_box)
                if overlap >= iou_threshold:
                    candidates.append((overlap, index, cluster))
            if candidates:
                _, _, chosen = max(candidates, key=lambda item: (item[0], -item[1]))
                chosen.members.append(detection)
                chosen.representative_box, fallback = _aggregate_box(chosen.members, box_strategy)
                chosen.box_fallback = chosen.box_fallback or fallback
            else:
                local_clusters.append(
                    _Cluster(
                        image_id=image_id,
                        class_key=class_key,
                        members=[detection],
                        representative_box=detection.box,
                    )
                )
        clusters.extend(local_clusters)

    consensus: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for cluster in clusters:
        members = sorted(cluster.members, key=lambda item: (item.source_id, -item.confidence))
        representative = cluster.representative_box or members[0].box
        source_votes = sorted(cluster.source_ids)
        pairwise_ious = [
            _iou(members[left].box, members[right].box)
            for left in range(len(members))
            for right in range(left + 1, len(members))
        ]
        label_class_ids = sorted(
            {member.label_class_id for member in members if member.label_class_id is not None}
        )
        labels = sorted({member.predicted_label for member in members})
        identity = {
            "image_id": cluster.image_id,
            "class_key": cluster.class_key,
            "sources": source_votes,
            "proposal_ids": sorted(
                member.proposal_id for member in members if member.proposal_id is not None
            ),
            "box": [round(value, 8) for value in representative],
        }
        entry = {
            "consensus_id": canonical_json_sha256(identity)[:20],
            "image_id": cluster.image_id,
            "label_class_id": label_class_ids[0] if len(label_class_ids) == 1 else None,
            "predicted_label": labels[0] if len(labels) == 1 else " / ".join(labels),
            "vote_count": len(source_votes),
            "required_votes": required_votes,
            "total_sources": len(source_ids),
            "source_ids": source_votes,
            "mean_confidence": round(
                sum(member.confidence for member in members) / len(members), 6
            ),
            "minimum_pairwise_iou": (round(min(pairwise_ious), 6) if pairwise_ious else None),
            "box": {
                "x_min": representative[0],
                "y_min": representative[1],
                "x_max": representative[2],
                "y_max": representative[3],
            },
            "box_strategy": box_strategy,
            "box_strategy_fallback": cluster.box_fallback,
            "members": [
                {
                    "source_id": member.source_id,
                    "source_kind": member.source_kind,
                    "proposal_id": member.proposal_id,
                    "confidence": member.confidence,
                    "label_class_id": member.label_class_id,
                    "predicted_label": member.predicted_label,
                    "box": {
                        "x_min": member.box[0],
                        "y_min": member.box[1],
                        "x_max": member.box[2],
                        "y_max": member.box[3],
                    },
                    "provenance": member.provenance,
                }
                for member in members
            ],
        }
        if len(source_votes) >= required_votes:
            consensus.append(entry)
        else:
            disagreements.append(
                {
                    **entry,
                    "reason": "insufficient_votes",
                    "votes_missing": required_votes - len(source_votes),
                }
            )

    consensus.sort(key=lambda item: (item["image_id"], item["consensus_id"]))
    disagreements.sort(key=lambda item: (item["image_id"], item["consensus_id"]))
    return {
        "schema_version": "detection-consensus-0001",
        "source_ids": source_ids,
        "source_count": len(source_ids),
        "required_votes": required_votes,
        "iou_threshold": iou_threshold,
        "confidence_threshold": confidence_threshold,
        "class_aware": class_aware,
        "box_strategy": box_strategy,
        "consensus_count": len(consensus),
        "disagreement_count": len(disagreements),
        "consensus": consensus,
        "disagreements": disagreements,
    }
