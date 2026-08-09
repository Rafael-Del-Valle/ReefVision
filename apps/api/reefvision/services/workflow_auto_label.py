"""Auto Label post-processing for reviewed workflow consensus results."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ActiveLearningRound,
    Annotation,
    AnnotationEvent,
    ImageAsset,
    LabelClass,
    ModelRegistration,
    ReviewQueue,
    ReviewQueueItem,
    WorkflowArtifact,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256

WORKFLOW_DISAGREEMENT_FORMULA_ID = "workflow_consensus_disagreement_v1"
WORKFLOW_DISAGREEMENT_FORMULA_VERSION = "1.0.0"


def _annotation_snapshot(annotation: Annotation) -> dict[str, Any]:
    return {
        "id": annotation.id,
        "image_id": annotation.image_id,
        "label_class_id": annotation.label_class_id,
        "x_min": annotation.x_min,
        "y_min": annotation.y_min,
        "x_max": annotation.x_max,
        "y_max": annotation.y_max,
        "source_type": annotation.source_type,
        "source_model_id": annotation.source_model_id,
        "source_prediction_id": annotation.source_prediction_id,
        "provenance_json": annotation.provenance_json,
        "created_by": annotation.created_by,
        "revision": annotation.revision,
    }


def materialize_consensus_annotations(
    session: Session,
    *,
    project_id: str,
    artifact: WorkflowArtifact,
    reviewed_by: str,
) -> dict[str, Any]:
    """Persist approved consensus detections as ordinary ReefVision annotations.

    IDs are deterministic from the consensus artifact and consensus detection identity so a
    workflow retry cannot duplicate an annotation. Entries without an unambiguous project class
    are preserved in the workflow artifact but are deliberately not materialized.
    """

    if artifact.data_type != "detection_consensus":
        raise ValidationError("Consensus materialization requires a detection_consensus artifact")
    payload = dict(artifact.payload_json or {})
    if payload.get("project_id") != project_id:
        raise ValidationError("Consensus artifact belongs to another project")

    detections = payload.get("detections", [])
    if not isinstance(detections, list):
        raise ValidationError("Consensus detections must be a list")

    image_ids = sorted(
        {
            str(item.get("image_id"))
            for item in detections
            if isinstance(item, dict) and item.get("image_id")
        }
    )
    class_ids = sorted(
        {
            str(item.get("label_class_id"))
            for item in detections
            if isinstance(item, dict) and item.get("label_class_id")
        }
    )
    images = {
        item.id: item
        for item in session.scalars(
            select(ImageAsset).where(
                ImageAsset.project_id == project_id,
                ImageAsset.id.in_(image_ids),
            )
        )
    }
    classes = {
        item.id: item
        for item in session.scalars(
            select(LabelClass).where(
                LabelClass.project_id == project_id,
                LabelClass.id.in_(class_ids),
            )
        )
    }

    annotation_ids: list[str] = []
    created_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    changed_image_ids: set[str] = set()

    for index, raw in enumerate(detections, start=1):
        if not isinstance(raw, dict):
            skipped.append({"index": index, "reason": "not_an_object"})
            continue
        image_id = str(raw.get("image_id") or "")
        label_class_id = str(raw.get("label_class_id") or "")
        consensus_id = str(raw.get("consensus_id") or canonical_json_sha256(raw)[:20])
        image = images.get(image_id)
        label_class = classes.get(label_class_id)
        if image is None:
            skipped.append(
                {
                    "consensus_id": consensus_id,
                    "image_id": image_id,
                    "reason": "image_not_found",
                }
            )
            continue
        if label_class is None:
            skipped.append(
                {
                    "consensus_id": consensus_id,
                    "image_id": image_id,
                    "label_class_id": label_class_id or None,
                    "reason": "unresolved_project_class",
                }
            )
            continue
        box = raw.get("box")
        if not isinstance(box, dict):
            skipped.append({"consensus_id": consensus_id, "reason": "missing_box"})
            continue
        try:
            raw_x_min = float(box["x_min"])
            raw_y_min = float(box["y_min"])
            raw_x_max = float(box["x_max"])
            raw_y_max = float(box["y_max"])
        except (KeyError, TypeError, ValueError):
            skipped.append({"consensus_id": consensus_id, "reason": "invalid_box"})
            continue

        x_min = min(max(raw_x_min, 0.0), float(image.width_px))
        y_min = min(max(raw_y_min, 0.0), float(image.height_px))
        x_max = min(max(raw_x_max, 0.0), float(image.width_px))
        y_max = min(max(raw_y_max, 0.0), float(image.height_px))
        if x_max <= x_min or y_max <= y_min:
            skipped.append({"consensus_id": consensus_id, "reason": "box_has_no_area"})
            continue

        annotation_id = str(
            uuid5(
                NAMESPACE_URL,
                f"reefvision:workflow-consensus:{artifact.id}:{consensus_id}",
            )
        )
        annotation_ids.append(annotation_id)
        existing = session.get(Annotation, annotation_id)
        if existing is not None:
            if existing.image_id != image_id or existing.label_class_id != label_class_id:
                raise ValidationError(
                    "Deterministic workflow annotation identity conflicts with existing data"
                )
            continue

        was_clamped = (x_min, y_min, x_max, y_max) != (
            raw_x_min,
            raw_y_min,
            raw_x_max,
            raw_y_max,
        )
        provenance = {
            "source": "workflow_consensus",
            "workflow_artifact_id": artifact.id,
            "workflow_run_id": artifact.workflow_run_id,
            "workflow_node_run_id": artifact.producer_node_run_id,
            "consensus_id": consensus_id,
            "vote_count": raw.get("vote_count"),
            "required_votes": raw.get("required_votes", payload.get("required_votes")),
            "total_sources": raw.get("total_sources", payload.get("source_count")),
            "source_ids": list(raw.get("source_ids", [])),
            "mean_confidence": raw.get("mean_confidence"),
            "minimum_pairwise_iou": raw.get("minimum_pairwise_iou"),
            "box_strategy": raw.get("box_strategy", payload.get("box_strategy")),
            "box_clamped_to_image": was_clamped,
            "members": list(raw.get("members", [])),
            "reviewed_by": reviewed_by,
        }
        annotation = Annotation(
            id=annotation_id,
            image_id=image_id,
            label_class_id=label_class.id,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            source_type="workflow_consensus",
            source_model_id=None,
            source_prediction_id=None,
            provenance_json=provenance,
            created_by=reviewed_by,
            revision=1,
        )
        session.add(annotation)
        session.add(
            AnnotationEvent(
                annotation_id=annotation.id,
                image_id=image_id,
                event_type="created",
                before_json=None,
                after_json=_annotation_snapshot(annotation),
                actor=reviewed_by,
            )
        )
        created_ids.append(annotation_id)
        changed_image_ids.add(image_id)

    for image_id in changed_image_ids:
        image = images[image_id]
        image.annotation_revision += 1
        if image.annotation_status == "unannotated":
            image.annotation_status = "annotated"

    session.flush()
    return {
        "artifact_id": artifact.id,
        "annotation_ids": annotation_ids,
        "created_annotation_ids": created_ids,
        "materialized_count": len(created_ids),
        "skipped_count": len(skipped),
        "skipped": skipped,
    }


def _local_model_ids(session: Session, project_id: str, source_ids: list[str]) -> list[str]:
    if not source_ids:
        return []
    return sorted(
        item.id
        for item in session.scalars(
            select(ModelRegistration).where(
                ModelRegistration.project_id == project_id,
                ModelRegistration.id.in_(source_ids),
            )
        )
    )


def ensure_disagreement_active_learning_round(
    session: Session,
    *,
    project_id: str,
    artifact: WorkflowArtifact,
    created_by: str,
) -> dict[str, Any] | None:
    """Create one idempotent Active Learning round from consensus-disagreement images."""

    if artifact.data_type != "detection_disagreements":
        raise ValidationError("Active Learning handoff requires detection_disagreements")
    payload = dict(artifact.payload_json or {})
    if payload.get("project_id") != project_id:
        raise ValidationError("Disagreement artifact belongs to another project")
    detections = payload.get("detections", [])
    if not isinstance(detections, list):
        raise ValidationError("Consensus disagreements must be a list")
    if not detections:
        return None

    by_image: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in detections:
        if isinstance(item, dict) and item.get("image_id"):
            by_image[str(item["image_id"])].append(item)
    if not by_image:
        return None

    valid_image_ids = set(
        session.scalars(
            select(ImageAsset.id).where(
                ImageAsset.project_id == project_id,
                ImageAsset.id.in_(sorted(by_image)),
            )
        )
    )
    by_image = {
        image_id: items
        for image_id, items in by_image.items()
        if image_id in valid_image_ids
    }
    if not by_image:
        return None

    identity = {
        "schema_version": "workflow-disagreement-active-learning-0001",
        "project_id": project_id,
        "source_artifact_id": artifact.id,
        "source_artifact_sha256": artifact.payload_sha256,
        "image_ids": sorted(by_image),
        "required_votes": payload.get("required_votes"),
        "source_ids": list(payload.get("source_ids", [])),
    }
    selection_sha256 = canonical_json_sha256(identity)
    existing = session.scalar(
        select(ActiveLearningRound).where(
            ActiveLearningRound.project_id == project_id,
            ActiveLearningRound.selection_sha256 == selection_sha256,
        )
    )
    if existing is not None:
        return {
            "round_id": existing.id,
            "review_queue_id": existing.review_queue_id,
            "selected_count": existing.selected_count,
            "created": False,
        }

    source_ids = [str(value) for value in payload.get("source_ids", [])]
    local_model_ids = _local_model_ids(session, project_id, source_ids)
    now = utc_now()
    queue = ReviewQueue(
        project_id=project_id,
        dataset_version_id=None,
        source_quality_control_run_id=None,
        regenerated_from_queue_id=None,
        scope_type="workflow_consensus",
        status="complete",
        formula_id=WORKFLOW_DISAGREEMENT_FORMULA_ID,
        formula_version=WORKFLOW_DISAGREEMENT_FORMULA_VERSION,
        configuration_json={
            "source": "workflow_consensus",
            "source_artifact_id": artifact.id,
            "required_votes": payload.get("required_votes"),
            "source_ids": source_ids,
        },
        input_checksums_json={"selection_sha256": selection_sha256},
        summary_json={},
        item_count=len(by_image),
        created_by=created_by,
        completed_at=now,
    )
    session.add(queue)
    session.flush()

    ranked: list[tuple[float, str, ReviewQueueItem]] = []
    for image_id, image_detections in by_image.items():
        disagreement_count = len(image_detections)
        votes_missing = max(
            int(item.get("votes_missing", 1) or 1) for item in image_detections
        )
        required_votes = max(
            int(item.get("required_votes", payload.get("required_votes", 1)) or 1)
            for item in image_detections
        )
        severity = min(votes_missing / max(required_votes, 1), 1.0)
        normalized_disagreement_count = min(disagreement_count / 5.0, 1.0)
        score = round(
            min(
                100.0,
                70.0
                + (20.0 * severity)
                + min(10.0, 2.0 * disagreement_count),
            ),
            2,
        )
        class_ids = sorted(
            {
                str(item["label_class_id"])
                for item in image_detections
                if item.get("label_class_id")
            }
        )
        reason = (
            f"Consensus disagreement: {disagreement_count} detection cluster(s) did not meet "
            f"the {required_votes}-of-{payload.get('source_count', len(source_ids))} vote rule; "
            f"maximum votes missing={votes_missing}."
        )
        item_input = {
            "image_id": image_id,
            "source_artifact_id": artifact.id,
            "consensus_ids": sorted(
                str(item.get("consensus_id") or "") for item in image_detections
            ),
            "required_votes": required_votes,
            "votes_missing": votes_missing,
        }
        queue_item = ReviewQueueItem(
            review_queue_id=queue.id,
            project_id=project_id,
            dataset_version_id=None,
            image_id=image_id,
            split=None,
            review_state="pending",
            score=score,
            rank_position=0,
            highest_qc_severity=None,
            label_class_ids_json=class_ids,
            model_ids_json=local_model_ids,
            related_issue_ids_json=[],
            signal_values_json={
                "consensus_disagreement_count": float(disagreement_count),
                "consensus_votes_missing": float(votes_missing),
            },
            normalized_signals_json={
                "consensus_disagreement_count": normalized_disagreement_count,
                "consensus_votes_missing": severity,
            },
            weights_json={
                "consensus_disagreement_count": 0.4,
                "consensus_votes_missing": 0.6,
            },
            score_breakdown_json=[
                {
                    "signal_id": "workflow_consensus_disagreement",
                    "label": "Auto Label model disagreement",
                    "raw_value": float(disagreement_count),
                    "normalized_value": max(normalized_disagreement_count, severity),
                    "weight": 100.0,
                    "contribution": score,
                    "description": reason,
                }
            ],
            input_checksum=canonical_json_sha256(item_input),
            reason_summary=reason,
        )
        ranked.append((score, image_id, queue_item))

    ranked.sort(key=lambda value: (-value[0], value[1]))
    for rank, (_, _, queue_item) in enumerate(ranked, start=1):
        queue_item.rank_position = rank
        session.add(queue_item)
    session.flush()

    queue.summary_json = {
        "source": "workflow_consensus",
        "selected_count": len(ranked),
        "source_artifact_id": artifact.id,
        "selection_sha256": selection_sha256,
    }
    manifest_items = [
        {
            "image_id": queue_item.image_id,
            "queue_item_id": queue_item.id,
            "rank_position": queue_item.rank_position,
            "score": queue_item.score,
            "input_checksum": queue_item.input_checksum,
            "reason_summary": queue_item.reason_summary,
        }
        for _, _, queue_item in ranked
    ]
    round_record = ActiveLearningRound(
        project_id=project_id,
        dataset_version_id=None,
        review_queue_id=queue.id,
        name="Workflow consensus disagreements",
        strategy="workflow_disagreement",
        status="open",
        requested_size=len(ranked),
        selected_count=len(ranked),
        model_ids_json=local_model_ids,
        strategy_config_json={
            "source": "workflow_consensus",
            "formula_id": WORKFLOW_DISAGREEMENT_FORMULA_ID,
            "required_votes": payload.get("required_votes"),
            "source_ids": source_ids,
        },
        selection_manifest_json={
            **identity,
            "schema_version": "active-learning-0001",
            "review_queue_id": queue.id,
            "strategy": "workflow_disagreement",
            "items": manifest_items,
        },
        selection_sha256=selection_sha256,
        feedback_summary_json={},
        created_by=created_by,
    )
    session.add(round_record)
    session.flush()
    return {
        "round_id": round_record.id,
        "review_queue_id": queue.id,
        "selected_count": round_record.selected_count,
        "created": True,
    }
