"""Fail-closed scoring adapter for immutable segmentation holdouts.

This read-only component scores verified mask snapshots against outputs from one
completed, evaluation-only inference job. It does not queue jobs, persist an
evaluation, accept proposals, or activate a model.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from reefvision.domain.segmentation_evaluation import (
    InstanceMaskMetrics,
    ScoredInstanceMask,
    instance_mask_metrics,
)
from reefvision.domain.segmentation_holdout import SegmentationHoldout
from reefvision.storage.segmentation_metric_masks import (
    MAX_MASK_PNG_BYTES,
    make_scored_mask,
    png_to_runs,
    polygon_to_runs,
)


class HoldoutImage(Protocol):
    image_id: str
    width_px: int
    height_px: int
    mask_annotation_snapshot_json: list[dict[str, Any]]


class EvaluationProposal(Protocol):
    image_id: str
    model_id: str
    inference_job_id: str
    model_checksum: str
    label_class_id: str | None
    confidence: float
    geometry_kind: str
    polygon_json: list[list[float]] | None
    mask_path: str | None
    mask_content_sha256: str | None
    review_status: str
    provenance_json: dict[str, Any] | None


@dataclass(frozen=True)
class ScoredSegmentationHoldout:
    dataset_version_id: str
    manifest_sha256: str
    split: str
    job_id: str
    model_id: str
    checkpoint_sha256: str
    metrics: InstanceMaskMetrics


def _verified_runs(
    snapshot: dict[str, Any],
    *,
    width: int,
    height: int,
    read_managed_raster: Callable[[str], bytes],
) -> tuple[tuple[int, int, int], ...]:
    kind = snapshot.get("geometry_kind")
    if kind in {"polygon", "polygon_mask"}:
        polygon = snapshot.get("polygon_json")
        if not isinstance(polygon, list):
            raise ValueError("Segmentation polygon is missing its source coordinates")
        return polygon_to_runs(polygon, width=width, height=height)
    if kind != "raster_mask":
        raise ValueError("A segmentation prediction cannot be scored from a box")
    path, digest = snapshot.get("mask_path"), snapshot.get("mask_content_sha256")
    if not isinstance(path, str) or not path or not isinstance(digest, str):
        raise ValueError("Raster mask is missing its immutable path or digest")
    if len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
        raise ValueError("Invalid source mask checksum")
    payload = read_managed_raster(path)
    if not isinstance(payload, bytes) or len(payload) > MAX_MASK_PNG_BYTES:
        raise ValueError("Raster mask payload is not valid managed PNG content")
    if sha256(payload).hexdigest() != digest.lower():
        raise ValueError("Raster mask differs from the immutable snapshot")
    return png_to_runs(payload, width=width, height=height)


def score_segmentation_holdout(
    *,
    holdout: SegmentationHoldout,
    snapshot_items: Sequence[HoldoutImage],
    proposals: Sequence[EvaluationProposal],
    dataset_version_id: str,
    manifest_sha256: str,
    inference_job_id: str,
    candidate_model_id: str,
    checkpoint_sha256: str,
    known_class_ids: Collection[str],
    inference_succeeded: bool,
    read_managed_raster: Callable[[str], bytes],
    operating_confidence: float = 0.25,
) -> ScoredSegmentationHoldout:
    """Bind all scored pixels to an immutable split and evaluation-only job.

    Caller MUST supply a holdout returned by SegmentationHoldoutService.prepare
    and resolve raster paths with the managed-project path resolver. This adapter
    verifies each actual decoded byte payload against its expected SHA-256.
    """
    if (
        not inference_succeeded
        or not dataset_version_id
        or not manifest_sha256
        or not inference_job_id
        or not candidate_model_id
        or len(checkpoint_sha256) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in checkpoint_sha256)
        or not known_class_ids
        or not holdout.image_ids
        or len(set(holdout.image_ids)) != len(holdout.image_ids)
    ):
        raise ValueError("Segmentation evaluation needs completed, identified, immutable inputs")
    if len(manifest_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in manifest_sha256):
        raise ValueError("Invalid immutable segmentation manifest digest")
    items_by_id = {item.image_id: item for item in snapshot_items}
    if len(items_by_id) != len(snapshot_items) or set(items_by_id) != set(holdout.image_ids):
        raise ValueError("Holdout image membership differs from the validated split")
    references = {(reference.image_id, reference.mask_id): reference for reference in holdout.masks}
    if len(references) != len(holdout.masks):
        raise ValueError("Duplicated verified mask reference")

    truth: list[ScoredInstanceMask] = []
    visited: set[tuple[str, str]] = set()
    for image_id in holdout.image_ids:
        item = items_by_id[image_id]
        if item.width_px < 1 or item.height_px < 1:
            raise ValueError("Invalid source image dimensions")
        for mask in item.mask_annotation_snapshot_json:
            if not isinstance(mask, dict) or not isinstance(mask.get("id"), str):
                raise ValueError("Malformed mask in validated holdout")
            key = (image_id, mask["id"])
            reference = references.get(key)
            if (
                reference is None
                or key in visited
                or mask.get("status") != "verified"
                or mask.get("label_class_id") != reference.class_id
                or mask.get("geometry_kind") != reference.geometry_kind
                or mask.get("mask_path") != reference.content_path
                or mask.get("mask_content_sha256") != reference.content_sha256
                or reference.class_id not in known_class_ids
            ):
                raise ValueError("Ground truth differs from the verified holdout snapshot")
            visited.add(key)
            runs = _verified_runs(
                mask,
                width=item.width_px,
                height=item.height_px,
                read_managed_raster=read_managed_raster,
            )
            truth.append(
                make_scored_mask(
                    runs,
                    image_id=image_id,
                    class_id=reference.class_id,
                    score=1.0,
                    width=item.width_px,
                    height=item.height_px,
                )
            )
    if visited != set(references):
        raise ValueError("Verified holdout reference is missing from snapshot pixels")

    predictions: list[ScoredInstanceMask] = []
    for proposal in proposals:
        if (
            proposal.image_id not in items_by_id
            or proposal.inference_job_id != inference_job_id
            or proposal.model_id != candidate_model_id
            or proposal.model_checksum.lower() != checkpoint_sha256.lower()
            or proposal.review_status != "evaluation_only"
            or not isinstance(proposal.provenance_json, dict)
            or proposal.provenance_json.get("evaluation_only") is not True
            or proposal.provenance_json.get("model_task") != "segment"
            or not isinstance(proposal.label_class_id, str)
            or proposal.label_class_id not in known_class_ids
        ):
            raise ValueError("Inference output is not an isolated segmentation evaluation proposal")
        item = items_by_id[proposal.image_id]
        runs = _verified_runs(
            {
                "geometry_kind": proposal.geometry_kind,
                "polygon_json": proposal.polygon_json,
                "mask_path": proposal.mask_path,
                "mask_content_sha256": proposal.mask_content_sha256,
            },
            width=item.width_px,
            height=item.height_px,
            read_managed_raster=read_managed_raster,
        )
        predictions.append(
            make_scored_mask(
                runs,
                image_id=proposal.image_id,
                class_id=proposal.label_class_id,
                score=proposal.confidence,
                width=item.width_px,
                height=item.height_px,
            )
        )
    metrics = instance_mask_metrics(
        truth,
        predictions,
        image_count=len(holdout.image_ids),
        operating_confidence=operating_confidence,
    )
    return ScoredSegmentationHoldout(
        dataset_version_id,
        manifest_sha256.lower(),
        holdout.split,
        inference_job_id,
        candidate_model_id,
        checkpoint_sha256.lower(),
        metrics,
    )
