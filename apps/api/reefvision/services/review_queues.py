"""Explainable review-queue generation and queue-item state transitions."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import mean
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    QualityControlRun,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.review_queues import ReviewQueueRepository
from reefvision.schemas.review_queues import (
    ReviewQueueCreateRequest,
    ReviewQueueItemPageResponse,
    ReviewQueueItemResponse,
    ReviewQueueItemSkipRequest,
    ReviewQueueResponse,
    ReviewScoreWeights,
)
from reefvision.services.quality_control import (
    CURRENT_QC_RULESET_VERSION,
    SEVERITY_SCORES,
    QualityControlService,
)
from reefvision.services.workflow_review_queue_integrity import queue_item_evidence_sha256
from reefvision.storage.datasets import canonical_json_sha256

FORMULA_ID = "review_priority_v1"
FORMULA_VERSION = "1.0.0"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ReviewQueueService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.quality_control = QualityControlService(session, settings)
        self.queues = ReviewQueueRepository(session)

    def _queue(self, queue_id: str) -> ReviewQueue:
        queue = self.queues.get_queue(queue_id)
        if queue is None:
            raise NotFoundError("Review queue not found")
        return queue

    def _item(self, item_id: str) -> ReviewQueueItem:
        item = self.queues.get_item(item_id)
        if item is None:
            raise NotFoundError("Review queue item not found")
        return item

    def _source_run(
        self,
        *,
        project_id: str,
        dataset_version_id: str | None,
        requested_run_id: str | None,
    ) -> QualityControlRun | None:
        if requested_run_id:
            run = self.quality_control._run(requested_run_id)
            if run.project_id != project_id or run.dataset_version_id != dataset_version_id:
                raise ValidationError(
                    "The selected QC run does not match the requested queue scope"
                )
            if run.status != "succeeded":
                raise ValidationError("Only completed quality-control runs can seed a review queue")
            return run
        return self.quality_control.quality_control.latest_complete_run(
            project_id,
            dataset_version_id=dataset_version_id,
        )

    def _signal_breakdown(
        self,
        *,
        signal_values: dict[str, float],
        normalized_signals: dict[str, float],
        weights: ReviewScoreWeights,
    ) -> tuple[list[dict[str, Any]], float]:
        weight_map = weights.model_dump(mode="json")
        total_weight = float(sum(weight_map.values()) or 1.0)
        labels = {
            "low_mean_confidence": "Low mean prediction confidence",
            "low_min_confidence": "Low minimum prediction confidence",
            "pending_proposals": "Many pending proposals",
            "rejection_rate": "High proposal rejection rate",
            "count_disagreement": "Model-versus-human count gap",
            "unresolved_qc_severity": "Unresolved QC severity",
            "rare_class_presence": "Rare-class presence",
            "edited_acceptance_rate": "Edited acceptance rate",
            "unreviewed_state": "Image not marked reviewed",
            "missing_group_metadata": "Missing group metadata",
            "incomplete_provenance": "Incomplete provenance",
            "recent_import": "Recently imported image",
            "stale_review_state": "Stale review state",
        }
        breakdown: list[dict[str, Any]] = []
        total_score = 0.0
        for signal_id, raw_value in signal_values.items():
            normalized_value = normalized_signals[signal_id]
            weight = float(weight_map[signal_id])
            contribution = (normalized_value * weight / total_weight) * 100.0
            total_score += contribution
            breakdown.append(
                {
                    "signal_id": signal_id,
                    "label": labels[signal_id],
                    "raw_value": float(raw_value),
                    "normalized_value": round(normalized_value, 6),
                    "weight": weight,
                    "contribution": round(contribution, 2),
                    "description": (
                        f"{labels[signal_id]} contributes according to the "
                        "configured deterministic weight."
                    ),
                }
            )
        breakdown.sort(key=lambda item: (-float(item["contribution"]), str(item["signal_id"])))
        return breakdown, round(total_score, 2)

    def _create_queue(
        self,
        *,
        project_id: str,
        dataset_version: DatasetVersion | None,
        request: ReviewQueueCreateRequest,
        regenerated_from_queue_id: str | None = None,
    ) -> ReviewQueue:
        project = self.quality_control._project(project_id)
        project_context = self.quality_control._build_project_context(project)
        split_by_image_id: dict[str, str | None] = {}
        scoped_image_ids: set[str]
        if dataset_version is None:
            scoped_image_ids = {image.image_id for image in project_context.images}
        else:
            version_items = self.quality_control.versions.items_for_version(
                dataset_version.id,
            )
            scoped_image_ids = {item.image_id for item in version_items}
            split_by_image_id = {item.image_id: item.split for item in version_items}
        source_run = self._source_run(
            project_id=project.id,
            dataset_version_id=dataset_version.id if dataset_version else None,
            requested_run_id=request.source_quality_control_run_id,
        )
        issues_by_image: dict[str, list[Any]] = defaultdict(list)
        if source_run is not None:
            for issue in self.quality_control.quality_control.issues_for_run(source_run.id):
                if issue.status not in {"open", "acknowledged"} or issue.image_id is None:
                    continue
                issues_by_image[issue.image_id].append(issue)
        scoped_images = [
            image for image in project_context.images if image.image_id in scoped_image_ids
        ]
        if not scoped_images:
            raise ValidationError("No images are available in the requested review-queue scope")

        class_counts: Counter[str] = Counter()
        for image in scoped_images:
            for annotation in project_context.annotations_by_image.get(image.image_id, []):
                if annotation.label_class_id:
                    class_counts[annotation.label_class_id] += 1
        max_class_count = max(class_counts.values(), default=1)
        queue = ReviewQueue(
            project_id=project.id,
            dataset_version_id=dataset_version.id if dataset_version else None,
            source_quality_control_run_id=source_run.id if source_run else None,
            regenerated_from_queue_id=regenerated_from_queue_id,
            scope_type="dataset_version" if dataset_version else "project",
            status="complete",
            formula_id=FORMULA_ID,
            formula_version=FORMULA_VERSION,
            configuration_json={
                "weights": request.signal_weights.model_dump(mode="json"),
                "review_below_confidence": request.review_below_confidence,
                "ruleset_version": CURRENT_QC_RULESET_VERSION,
                "source_quality_control_run_id": source_run.id if source_run else None,
            },
            input_checksums_json={},
            summary_json={},
            created_by=request.created_by or "local_user",
            completed_at=_utc_now(),
        )
        self.queues.add_queue(queue)
        self.session.flush()

        items: list[ReviewQueueItem] = []
        reference_timestamps = [
            _as_utc(value)
            for image in scoped_images
            for value in (image.created_at, image.updated_at)
            if value is not None
        ]
        reference_time = max(reference_timestamps) if reference_timestamps else _utc_now()
        for image in scoped_images:
            annotations = project_context.annotations_by_image.get(image.image_id, [])
            predictions = project_context.predictions_by_image.get(image.image_id, [])
            pending_predictions = [
                item
                for item in predictions
                if item.review_status == "pending"
                and (
                    request.review_below_confidence is None
                    or item.confidence <= request.review_below_confidence
                )
            ]
            # Explicit confidence gating is a review-selection rule, not a
            # claim that excluded model predictions were researcher-verified.
            if request.review_below_confidence is not None and not pending_predictions:
                continue
            reviewed_predictions = [
                item
                for item in predictions
                if item.review_status in {"accepted", "edited_and_accepted", "rejected"}
            ]
            accepted_predictions = [
                item
                for item in predictions
                if item.review_status in {"accepted", "edited_and_accepted"}
            ]
            rejected_predictions = [
                item for item in predictions if item.review_status == "rejected"
            ]
            image_issues = issues_by_image.get(image.image_id, [])
            annotation_count = len(annotations)
            proposal_count = len(pending_predictions) + len(accepted_predictions)
            low_mean_confidence = (
                max(0.0, 1.0 - mean(item.confidence for item in pending_predictions))
                if pending_predictions
                else 0.0
            )
            low_min_confidence = (
                max(0.0, 1.0 - min(item.confidence for item in pending_predictions))
                if pending_predictions
                else 0.0
            )
            rejection_rate = (
                len(rejected_predictions) / len(reviewed_predictions)
                if reviewed_predictions
                else 0.0
            )
            count_disagreement = abs(annotation_count - proposal_count) / max(
                annotation_count, proposal_count, 1
            )
            unresolved_qc_severity = max(
                (SEVERITY_SCORES.get(issue.severity, 0.0) for issue in image_issues),
                default=0.0,
            )
            class_ids = sorted(
                {
                    annotation.label_class_id
                    for annotation in annotations
                    if annotation.label_class_id is not None
                }
            )
            rare_class_presence = max(
                (
                    1.0 - (class_counts[class_id] / max_class_count)
                    for class_id in class_ids
                    if class_counts[class_id] > 0
                ),
                default=0.0,
            )
            edited_acceptance_rate = (
                sum(1 for item in accepted_predictions if item.was_edited)
                / len(accepted_predictions)
                if accepted_predictions
                else 0.0
            )
            unreviewed_state = 1.0 if image.annotation_status != "reviewed" else 0.0
            missing_group_metadata = (
                0.0 if image.group_key is not None and image.group_key.strip() else 1.0
            )
            provenance_total = sum(
                1
                for annotation in annotations
                if annotation.source_type in {"accepted_prediction", "assist_mask"}
            ) + len(accepted_predictions)
            provenance_missing = sum(
                1
                for annotation in annotations
                if annotation.source_type in {"accepted_prediction", "assist_mask"}
                and not annotation.provenance_json
            ) + sum(1 for item in accepted_predictions if not item.provenance_json)
            incomplete_provenance = (
                provenance_missing / provenance_total if provenance_total else 0.0
            )
            recent_import = 0.0
            if image.created_at is not None:
                age_days = max(
                    (reference_time - _as_utc(image.created_at)).total_seconds() / 86_400.0,
                    0.0,
                )
                recent_import = max(0.0, 1.0 - (age_days / 7.0))
            stale_review_state = 0.0
            if image.updated_at is not None and image.annotation_status != "reviewed":
                age_days = max(
                    (reference_time - _as_utc(image.updated_at)).total_seconds() / 86_400.0,
                    0.0,
                )
                stale_review_state = min(age_days / 30.0, 1.0)
            signal_values = {
                "low_mean_confidence": low_mean_confidence,
                "low_min_confidence": low_min_confidence,
                "pending_proposals": float(len(pending_predictions)),
                "rejection_rate": rejection_rate,
                "count_disagreement": count_disagreement,
                "unresolved_qc_severity": unresolved_qc_severity,
                "rare_class_presence": rare_class_presence,
                "edited_acceptance_rate": edited_acceptance_rate,
                "unreviewed_state": unreviewed_state,
                "missing_group_metadata": missing_group_metadata,
                "incomplete_provenance": incomplete_provenance,
                "recent_import": recent_import,
                "stale_review_state": stale_review_state,
            }
            normalized_signals = {
                "low_mean_confidence": min(max(low_mean_confidence, 0.0), 1.0),
                "low_min_confidence": min(max(low_min_confidence, 0.0), 1.0),
                "pending_proposals": min(len(pending_predictions) / 10.0, 1.0),
                "rejection_rate": min(max(rejection_rate, 0.0), 1.0),
                "count_disagreement": min(max(count_disagreement, 0.0), 1.0),
                "unresolved_qc_severity": min(max(unresolved_qc_severity, 0.0), 1.0),
                "rare_class_presence": min(max(rare_class_presence, 0.0), 1.0),
                "edited_acceptance_rate": min(max(edited_acceptance_rate, 0.0), 1.0),
                "unreviewed_state": min(max(unreviewed_state, 0.0), 1.0),
                "missing_group_metadata": min(max(missing_group_metadata, 0.0), 1.0),
                "incomplete_provenance": min(max(incomplete_provenance, 0.0), 1.0),
                "recent_import": min(max(recent_import, 0.0), 1.0),
                "stale_review_state": min(max(stale_review_state, 0.0), 1.0),
            }
            breakdown, score = self._signal_breakdown(
                signal_values=signal_values,
                normalized_signals=normalized_signals,
                weights=request.signal_weights,
            )
            severity_order = {"error": 3, "warning": 2, "info": 1}
            highest_severity = (
                max(
                    image_issues,
                    key=lambda issue: severity_order.get(issue.severity, 0),
                ).severity
                if image_issues
                else None
            )
            model_ids = sorted({prediction.model_id for prediction in predictions})
            reason_summary = ", ".join(
                f"{entry['label']}: +{entry['contribution']:.2f}"
                for entry in breakdown[:4]
                if float(entry["contribution"]) > 0
            )
            item_input = {
                "image_id": image.image_id,
                "split": split_by_image_id.get(image.image_id),
                "annotation_status": image.annotation_status,
                "annotation_count": annotation_count,
                "prediction_ids": sorted(item.id for item in predictions),
                "issue_ids": sorted(issue.id for issue in image_issues),
                "signal_values": signal_values,
                "weights": request.signal_weights.model_dump(mode="json"),
            }
            items.append(
                ReviewQueueItem(
                    review_queue_id=queue.id,
                    project_id=project.id,
                    dataset_version_id=dataset_version.id if dataset_version else None,
                    image_id=image.image_id,
                    split=split_by_image_id.get(image.image_id),
                    review_state="pending",
                    score=score,
                    rank_position=0,
                    highest_qc_severity=highest_severity,
                    label_class_ids_json=class_ids,
                    model_ids_json=model_ids,
                    related_issue_ids_json=sorted(issue.id for issue in image_issues),
                    signal_values_json=signal_values,
                    normalized_signals_json=normalized_signals,
                    weights_json=request.signal_weights.model_dump(mode="json"),
                    score_breakdown_json=breakdown,
                    input_checksum=canonical_json_sha256(item_input),
                    reason_summary=reason_summary or None,
                )
            )

        items.sort(key=lambda item: (-item.score, item.image_id))
        for position, item in enumerate(items, start=1):
            item.rank_position = position
        queue.item_count = len(items)
        queue.input_checksums_json = {
            "queue_scope_sha256": canonical_json_sha256(
                {
                    "image_ids": sorted(item.image_id for item in items),
                    "scores": {item.image_id: item.score for item in items},
                    "source_quality_control_run_id": source_run.id if source_run else None,
                }
            ),
            "item_count": len(items),
            "integrity_schema_version": "qc-review-queue-v3",
            # Preserve immutable scientific explanations, not mutable reviewer
            # state, across saved Workflow Builder retries.
            "item_evidence_sha256": queue_item_evidence_sha256(items),
            # Retain the scoring contract independently from the image/score
            # checksum. A saved Workflow Builder retry must not silently
            # re-label its formula, ruleset or weight provenance.
            "scoring_provenance_sha256": canonical_json_sha256(
                {
                    "formula_id": queue.formula_id,
                    "formula_version": queue.formula_version,
                    "configuration": queue.configuration_json,
                    "integrity_schema_version": "qc-review-queue-v3",
                }
            ),
        }
        queue.summary_json = {
            "average_score": round(mean(item.score for item in items), 2) if items else 0.0,
            "counts_by_severity": dict(
                Counter(item.highest_qc_severity for item in items if item.highest_qc_severity)
            ),
            "counts_by_split": dict(Counter(item.split or "unspecified" for item in items)),
            "top_image_ids": [item.image_id for item in items[:10]],
        }
        self.queues.add_items(items)
        self.session.commit()
        self.session.refresh(queue)
        return queue

    def create_queue_for_project(
        self,
        project_id: str,
        request: ReviewQueueCreateRequest,
    ) -> ReviewQueueResponse:
        return ReviewQueueResponse.model_validate(
            self._create_queue(project_id=project_id, dataset_version=None, request=request)
        )

    def create_queue_for_dataset_version(
        self,
        version_id: str,
        request: ReviewQueueCreateRequest,
    ) -> ReviewQueueResponse:
        version = self.quality_control._version(version_id)
        return ReviewQueueResponse.model_validate(
            self._create_queue(
                project_id=version.project_id,
                dataset_version=version,
                request=request,
            )
        )

    def list_queues(
        self,
        project_id: str,
        *,
        dataset_version_id: str | None = None,
    ) -> list[ReviewQueueResponse]:
        self.quality_control._project(project_id)
        return [
            ReviewQueueResponse.model_validate(item)
            for item in self.queues.list_queues(project_id, dataset_version_id=dataset_version_id)
        ]

    def get_queue(self, queue_id: str) -> ReviewQueueResponse:
        return ReviewQueueResponse.model_validate(self._queue(queue_id))

    def list_items(
        self,
        queue_id: str,
        *,
        page: int,
        page_size: int,
        label_class_id: str | None,
        split: str | None,
        qc_severity: str | None,
        review_state: str | None,
        model_id: str | None,
    ) -> ReviewQueueItemPageResponse:
        self._queue(queue_id)
        items, total, pages = self.queues.paged_items(
            queue_id,
            page=page,
            page_size=page_size,
            label_class_id=label_class_id,
            split=split,
            qc_severity=qc_severity,
            review_state=review_state,
            model_id=model_id,
        )
        return ReviewQueueItemPageResponse(
            items=[ReviewQueueItemResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def _record_single_item_triage(
        self, item: ReviewQueueItem, *, action: str, reason: str | None = None
    ) -> None:
        """Append server-generated state-transition evidence in the same transaction.

        The existing single-item API has no authenticated actor field. Its
        local_user label is not proof of reviewer identity or biological review.
        """
        self.session.add(
            ReviewQueueItemEvent(
                review_queue_id=item.review_queue_id,
                review_queue_item_id=item.id,
                project_id=item.project_id,
                client_request_id=str(uuid4()),
                event_type=f"triage_{action}",
                actor="local_user",
                comment=reason,
            )
        )

    def start_item(self, item_id: str) -> ReviewQueueItemResponse:
        item = self._item(item_id)
        if item.review_state != "pending":
            raise ConflictError("Only pending queue items can be started")
        item.review_state = "in_progress"
        item.started_at = _utc_now()
        self._record_single_item_triage(item, action="start")
        self.session.commit()
        self.session.refresh(item)
        return ReviewQueueItemResponse.model_validate(item)

    def complete_item(self, item_id: str) -> ReviewQueueItemResponse:
        item = self._item(item_id)
        if item.review_state not in {"pending", "in_progress"}:
            raise ConflictError("Only pending or in-progress queue items can be completed")
        item.review_state = "completed"
        if item.started_at is None:
            item.started_at = _utc_now()
        item.completed_at = _utc_now()
        self._record_single_item_triage(item, action="complete")
        self.session.commit()
        self.session.refresh(item)
        return ReviewQueueItemResponse.model_validate(item)

    def skip_item(
        self,
        item_id: str,
        request: ReviewQueueItemSkipRequest,
    ) -> ReviewQueueItemResponse:
        item = self._item(item_id)
        if item.review_state not in {"pending", "in_progress"}:
            raise ConflictError("Only pending or in-progress queue items can be skipped")
        item.review_state = "skipped"
        item.skip_reason = request.reason
        item.completed_at = None
        self._record_single_item_triage(item, action="skip", reason=request.reason)
        self.session.commit()
        self.session.refresh(item)
        return ReviewQueueItemResponse.model_validate(item)

    def return_item(self, item_id: str) -> ReviewQueueItemResponse:
        item = self._item(item_id)
        if item.review_state != "skipped":
            raise ConflictError("Only skipped queue items can be returned to the queue")
        item.review_state = "pending"
        item.returned_at = _utc_now()
        self._record_single_item_triage(item, action="return")
        self.session.commit()
        self.session.refresh(item)
        return ReviewQueueItemResponse.model_validate(item)

    def regenerate(self, queue_id: str) -> ReviewQueueResponse:
        queue = self._queue(queue_id)
        request = ReviewQueueCreateRequest(
            source_quality_control_run_id=queue.source_quality_control_run_id,
            signal_weights=ReviewScoreWeights.model_validate(
                queue.configuration_json.get("weights", {})
            ),
            created_by=queue.created_by,
            review_below_confidence=queue.configuration_json.get("review_below_confidence"),
        )
        if queue.dataset_version_id is not None:
            dataset_version = self.quality_control._version(queue.dataset_version_id)
        else:
            dataset_version = None
        regenerated = self._create_queue(
            project_id=queue.project_id,
            dataset_version=dataset_version,
            request=request,
            regenerated_from_queue_id=queue.id,
        )
        return ReviewQueueResponse.model_validate(regenerated)
