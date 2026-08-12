"""N-of-M classification consensus and canonical image-label materialization."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ImageAsset, ImageLabel, LabelClass, WorkflowArtifact
from reefvision.domain.errors import ValidationError

_CONSENSUS_NAMESPACE = UUID("0d73b98e-bc89-43f1-b721-18b30045399e")


def _consensus_id(image_id: str, label_class_id: str, voters: list[str]) -> str:
    stable = "|".join([image_id, label_class_id, *sorted(voters)])
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def build_classification_consensus(
    sources: list[dict[str, Any]],
    *,
    required_votes: int = 2,
    confidence_threshold: float = 0.0,
) -> dict[str, Any]:
    """Vote on one top-ranked class per source and image.

    Each source may cast at most one vote for an image. A unique highest-vote class
    must reach ``required_votes``; ties are retained as disagreements even when each
    tied class individually meets the vote threshold.
    """

    if len(sources) < 2:
        raise ValidationError("Classification Consensus requires at least two sources")
    if required_votes < 1 or required_votes > len(sources):
        raise ValidationError("required_votes must be between 1 and the source count")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValidationError("confidence_threshold must be between 0 and 1")

    source_ids: list[str] = []
    label_sets: set[str] = set()
    votes_by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, source in enumerate(sources):
        source_id = str(
            source.get("source_id")
            or source.get("source_model_id")
            or f"classification-source-{index + 1}"
        )
        if source_id in source_ids:
            raise ValidationError("Classification Consensus source IDs must be unique")
        source_ids.append(source_id)
        label_set = str(source.get("label_set") or "default")
        label_sets.add(label_set)

        predictions = source.get("predictions", [])
        if not isinstance(predictions, list):
            raise ValidationError("Classification prediction payload is invalid")
        by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for raw in predictions:
            if not isinstance(raw, dict):
                continue
            image_id = str(raw.get("image_id") or "")
            label_class_id = str(raw.get("label_class_id") or "")
            if not image_id or not label_class_id:
                continue
            confidence = float(raw.get("confidence") or 0.0)
            if confidence < confidence_threshold:
                continue
            by_image[image_id].append(raw)
        for image_id, candidates in by_image.items():
            top = min(
                candidates,
                key=lambda item: (
                    int(item.get("rank") or 10**9),
                    -float(item.get("confidence") or 0.0),
                    str(item.get("label_class_id") or ""),
                ),
            )
            votes_by_image[image_id].append(
                {
                    "source_id": source_id,
                    "prediction_id": top.get("prediction_id"),
                    "label_class_id": str(top["label_class_id"]),
                    "confidence": float(top.get("confidence") or 0.0),
                    "rank": int(top.get("rank") or 1),
                }
            )

    if len(label_sets) != 1:
        raise ValidationError("Classification Consensus requires the same label_set")
    label_set = next(iter(label_sets))

    consensus: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    all_images = sorted(votes_by_image)
    for image_id in all_images:
        votes = votes_by_image[image_id]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for vote in votes:
            grouped[str(vote["label_class_id"])].append(vote)
        ranked = sorted(
            grouped.items(),
            key=lambda item: (
                -len(item[1]),
                -sum(float(vote["confidence"]) for vote in item[1]) / len(item[1]),
                item[0],
            ),
        )
        if not ranked:
            disagreements.append(
                {
                    "image_id": image_id,
                    "reason": "no_eligible_votes",
                    "source_count": len(source_ids),
                    "vote_count": 0,
                    "votes": [],
                }
            )
            continue
        winning_class, winning_votes = ranked[0]
        winning_count = len(winning_votes)
        tied = len(ranked) > 1 and len(ranked[1][1]) == winning_count
        if winning_count < required_votes or tied:
            disagreements.append(
                {
                    "image_id": image_id,
                    "reason": "tie" if tied else "insufficient_votes",
                    "required_votes": required_votes,
                    "source_count": len(source_ids),
                    "vote_count": winning_count,
                    "votes": votes,
                    "votes_by_class": {
                        class_id: len(class_votes) for class_id, class_votes in ranked
                    },
                }
            )
            continue
        confidences = [float(vote["confidence"]) for vote in winning_votes]
        voters = [str(vote["source_id"]) for vote in winning_votes]
        consensus.append(
            {
                "consensus_id": _consensus_id(image_id, winning_class, voters),
                "image_id": image_id,
                "label_class_id": winning_class,
                "label_set": label_set,
                "vote_count": winning_count,
                "source_count": len(source_ids),
                "vote_fraction": winning_count / len(source_ids),
                "mean_confidence": sum(confidences) / len(confidences),
                "min_confidence": min(confidences),
                "max_confidence": max(confidences),
                "voters": winning_votes,
            }
        )

    return {
        "schema_version": "classification-consensus-0001",
        "source_ids": source_ids,
        "source_count": len(source_ids),
        "label_set": label_set,
        "required_votes": required_votes,
        "confidence_threshold": confidence_threshold,
        "consensus_count": len(consensus),
        "disagreement_count": len(disagreements),
        "consensus": consensus,
        "disagreements": disagreements,
    }


def materialize_classification_consensus_labels(
    session: Session,
    *,
    project_id: str,
    artifact: WorkflowArtifact,
    reviewed_by: str,
) -> dict[str, Any]:
    """Persist approved classification consensus as ordinary verified ImageLabels."""

    payload = dict(artifact.payload_json or {})
    if payload.get("project_id") != project_id or artifact.data_type != "classification_consensus":
        raise ValidationError("Classification consensus artifact does not belong to this project")
    labels = payload.get("labels", [])
    if not isinstance(labels, list):
        raise ValidationError("Classification consensus labels are invalid")
    label_set = str(payload.get("label_set") or "default")
    created_ids: list[str] = []
    reused_ids: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw in labels:
        if not isinstance(raw, dict):
            continue
        consensus_id = str(raw.get("consensus_id") or "")
        image_id = str(raw.get("image_id") or "")
        label_class_id = str(raw.get("label_class_id") or "")
        if not consensus_id or not image_id or not label_class_id:
            skipped.append({"consensus_id": consensus_id, "reason": "missing_identity"})
            continue
        image = session.get(ImageAsset, image_id)
        label_class = session.get(LabelClass, label_class_id)
        if image is None or image.project_id != project_id:
            skipped.append({"consensus_id": consensus_id, "reason": "image_scope_mismatch"})
            continue
        if label_class is None or label_class.project_id != project_id:
            skipped.append({"consensus_id": consensus_id, "reason": "class_scope_mismatch"})
            continue

        deterministic_id = str(uuid5(_CONSENSUS_NAMESPACE, f"{artifact.id}:{consensus_id}"))
        existing = session.scalar(
            select(ImageLabel).where(
                ImageLabel.image_id == image_id,
                ImageLabel.label_class_id == label_class_id,
                ImageLabel.label_set == label_set,
                ImageLabel.deleted_at.is_(None),
            )
        )
        if existing is not None:
            reused_ids.append(existing.id)
            continue
        record = ImageLabel(
            id=deterministic_id,
            image_id=image_id,
            label_class_id=label_class_id,
            label_set=label_set,
            confidence=float(raw.get("mean_confidence") or 0.0),
            source_type="workflow_consensus",
            source_model_id=None,
            source_prediction_id=None,
            provenance_json={
                "source": "workflow_classification_consensus",
                "workflow_artifact_id": artifact.id,
                "workflow_run_id": artifact.workflow_run_id,
                "consensus_id": consensus_id,
                "required_votes": payload.get("required_votes"),
                "source_count": raw.get("source_count"),
                "vote_count": raw.get("vote_count"),
                "vote_fraction": raw.get("vote_fraction"),
                "voters": list(raw.get("voters", [])),
            },
            status="verified",
            created_by=reviewed_by or "local_user",
            revision=1,
        )
        session.add(record)
        created_ids.append(record.id)

    session.flush()
    return {
        "created_image_label_ids": created_ids,
        "reused_image_label_ids": reused_ids,
        "skipped": skipped,
        "created_count": len(created_ids),
        "reused_count": len(reused_ids),
    }
