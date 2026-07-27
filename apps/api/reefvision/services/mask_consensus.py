"""Class-aware one-to-one matching and pixel aggregation for independent masks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from reefvision.domain.errors import ValidationError

MaskArray = NDArray[np.bool_]
MaskAggregation = Literal["intersection", "pixel_majority", "union", "best_confidence"]


@dataclass(frozen=True, slots=True)
class IndependentMaskCandidate:
    """One independently generated instance mask from one model branch."""

    candidate_id: str
    branch_id: str
    image_id: str
    class_key: str
    confidence: float
    mask: MaskArray
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaskConsensusGroup:
    group_id: str
    image_id: str
    class_key: str
    required_votes: int
    aggregation: MaskAggregation
    candidate_ids: tuple[str, ...]
    branch_ids: tuple[str, ...]
    pairwise_iou: dict[str, float]
    confidence: float
    mask: MaskArray


@dataclass(frozen=True, slots=True)
class MaskConsensusResult:
    input_count: int
    matched_group_count: int
    consensus_group_count: int
    rejected_group_count: int
    groups: tuple[MaskConsensusGroup, ...]
    warnings: tuple[str, ...]


def _validated_mask(candidate: IndependentMaskCandidate) -> MaskArray:
    values = np.asarray(candidate.mask)
    if values.ndim != 2:
        raise ValidationError("Independent consensus masks must be two-dimensional")
    mask = np.asarray(values > 0, dtype=bool)
    if not bool(mask.any()):
        raise ValidationError(
            f"Independent consensus candidate {candidate.candidate_id!r} is empty"
        )
    if not 0 <= float(candidate.confidence) <= 1:
        raise ValidationError("Independent consensus confidence must be between 0 and 1")
    if not candidate.branch_id.strip() or not candidate.class_key.strip():
        raise ValidationError("Independent consensus candidates require branch and class keys")
    return mask


def mask_iou(first: MaskArray, second: MaskArray) -> float:
    if first.shape != second.shape:
        raise ValidationError("Masks compared for consensus must share dimensions")
    intersection = int(np.count_nonzero(first & second))
    union = int(np.count_nonzero(first | second))
    return intersection / union if union else 0.0


def _pair_key(first: IndependentMaskCandidate, second: IndependentMaskCandidate) -> str:
    left, right = sorted((first.candidate_id, second.candidate_id))
    return f"{left}|{right}"


def _aggregate(
    candidates: list[IndependentMaskCandidate],
    *,
    aggregation: MaskAggregation,
    required_votes: int,
) -> MaskArray:
    stack = np.stack([np.asarray(item.mask, dtype=bool) for item in candidates], axis=0)
    if aggregation == "intersection":
        return np.asarray(np.all(stack, axis=0), dtype=np.bool_)
    if aggregation == "pixel_majority":
        return np.asarray(
            np.count_nonzero(stack, axis=0) >= required_votes,
            dtype=np.bool_,
        )
    if aggregation == "union":
        return np.asarray(np.any(stack, axis=0), dtype=np.bool_)
    if aggregation == "best_confidence":
        selected = max(candidates, key=lambda item: (item.confidence, item.candidate_id))
        return np.asarray(selected.mask, dtype=bool).copy()
    raise ValidationError(f"Unsupported mask consensus aggregation: {aggregation}")


def build_mask_consensus(
    candidates: list[IndependentMaskCandidate],
    *,
    required_votes: int = 2,
    iou_threshold: float = 0.3,
    aggregation: MaskAggregation = "pixel_majority",
) -> MaskConsensusResult:
    """Match independent instances without allowing duplicate votes from one branch.

    Candidate pairs are considered only when image and class match. Pair edges are
    processed from highest to lowest mask IoU. Components are merged only when their
    branch sets are disjoint, which enforces at most one vote per model branch while
    remaining deterministic for crowded scenes.
    """

    if required_votes < 2:
        raise ValidationError("Mask consensus requires at least two independent votes")
    if not 0 <= iou_threshold <= 1:
        raise ValidationError("Mask consensus IoU threshold must be between 0 and 1")
    if aggregation not in {"intersection", "pixel_majority", "union", "best_confidence"}:
        raise ValidationError(f"Unsupported mask consensus aggregation: {aggregation}")

    normalized: list[IndependentMaskCandidate] = []
    shape_by_image: dict[str, tuple[int, int]] = {}
    seen_ids: set[str] = set()
    for item in candidates:
        if item.candidate_id in seen_ids:
            raise ValidationError("Independent consensus candidate IDs must be unique")
        seen_ids.add(item.candidate_id)
        mask = _validated_mask(item)
        mask_shape = (int(mask.shape[0]), int(mask.shape[1]))
        existing_shape = shape_by_image.setdefault(item.image_id, mask_shape)
        if existing_shape != mask_shape:
            raise ValidationError("All masks for one image must share dimensions")
        normalized.append(
            IndependentMaskCandidate(
                candidate_id=item.candidate_id,
                branch_id=item.branch_id,
                image_id=item.image_id,
                class_key=item.class_key,
                confidence=float(item.confidence),
                mask=mask,
                provenance=dict(item.provenance),
            )
        )

    parent = {item.candidate_id: item.candidate_id for item in normalized}
    component_branches = {item.candidate_id: {item.branch_id} for item in normalized}

    def find(candidate_id: str) -> str:
        root = candidate_id
        while parent[root] != root:
            root = parent[root]
        while parent[candidate_id] != candidate_id:
            next_id = parent[candidate_id]
            parent[candidate_id] = root
            candidate_id = next_id
        return root

    pairwise: dict[str, float] = {}
    edges: list[tuple[float, str, str]] = []
    ordered = sorted(
        normalized,
        key=lambda item: (item.image_id, item.class_key, item.branch_id, item.candidate_id),
    )
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if second.image_id != first.image_id:
                if second.image_id > first.image_id:
                    break
                continue
            if second.class_key != first.class_key or second.branch_id == first.branch_id:
                continue
            score = mask_iou(first.mask, second.mask)
            pairwise[_pair_key(first, second)] = score
            if score >= iou_threshold:
                edges.append((score, first.candidate_id, second.candidate_id))

    for _score, first_id, second_id in sorted(
        edges,
        key=lambda item: (-item[0], item[1], item[2]),
    ):
        first_root = find(first_id)
        second_root = find(second_id)
        if first_root == second_root:
            continue
        if component_branches[first_root] & component_branches[second_root]:
            continue
        # Stable root selection makes manifests reproducible.
        keep, merge = sorted((first_root, second_root))
        parent[merge] = keep
        component_branches[keep] |= component_branches[merge]
        component_branches.pop(merge, None)

    components: dict[str, list[IndependentMaskCandidate]] = {}
    for item in normalized:
        components.setdefault(find(item.candidate_id), []).append(item)

    groups: list[MaskConsensusGroup] = []
    warnings: list[str] = []
    rejected = 0
    for root, members in sorted(components.items()):
        members = sorted(members, key=lambda item: (item.branch_id, item.candidate_id))
        if len(members) < required_votes:
            rejected += 1
            continue
        consensus_mask = _aggregate(
            members,
            aggregation=aggregation,
            required_votes=required_votes,
        )
        if not bool(consensus_mask.any()):
            rejected += 1
            warnings.append(f"Consensus group {root} became empty under {aggregation} aggregation.")
            continue
        member_ids = {item.candidate_id for item in members}
        group_pairs = {
            key: value for key, value in pairwise.items() if set(key.split("|")) <= member_ids
        }
        groups.append(
            MaskConsensusGroup(
                group_id=root,
                image_id=members[0].image_id,
                class_key=members[0].class_key,
                required_votes=required_votes,
                aggregation=aggregation,
                candidate_ids=tuple(item.candidate_id for item in members),
                branch_ids=tuple(item.branch_id for item in members),
                pairwise_iou=group_pairs,
                confidence=float(sum(item.confidence for item in members) / len(members)),
                mask=np.asarray(consensus_mask, dtype=bool),
            )
        )

    matched_groups = sum(len(items) > 1 for items in components.values())
    return MaskConsensusResult(
        input_count=len(normalized),
        matched_group_count=matched_groups,
        consensus_group_count=len(groups),
        rejected_group_count=rejected,
        groups=tuple(groups),
        warnings=tuple(warnings),
    )
