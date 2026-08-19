"""Reproducible active-learning acquisition rounds built on review queues."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ActiveLearningRound,
    ClassificationPrediction,
    DatasetVersion,
    ImageAsset,
    ModelRegistration,
    PredictionProposal,
    Project,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.active_learning import (
    ActiveLearningFeedbackResponse,
    ActiveLearningRoundCreateRequest,
    ActiveLearningRoundResponse,
)
from reefvision.schemas.dataset_versions import DatasetVersionCreateRequest, SplitRatios
from reefvision.schemas.review_queues import ReviewQueueCreateRequest, ReviewScoreWeights
from reefvision.services.mask_aware_dataset_versions import MaskAwareDatasetVersionService
from reefvision.services.review_queues import ReviewQueueService
from reefvision.storage.datasets import canonical_json_sha256

_STRATEGY_WEIGHTS: dict[str, ReviewScoreWeights] = {
    "hybrid": ReviewScoreWeights(),
    "uncertainty": ReviewScoreWeights(
        low_mean_confidence=34,
        low_min_confidence=22,
        pending_proposals=12,
        rejection_rate=8,
        count_disagreement=14,
        unresolved_qc_severity=6,
        rare_class_presence=4,
        edited_acceptance_rate=6,
        unreviewed_state=8,
        missing_group_metadata=0,
        incomplete_provenance=2,
        recent_import=2,
        stale_review_state=2,
    ),
    "rare_class": ReviewScoreWeights(
        low_mean_confidence=16,
        low_min_confidence=8,
        pending_proposals=8,
        rejection_rate=6,
        count_disagreement=8,
        unresolved_qc_severity=10,
        rare_class_presence=38,
        edited_acceptance_rate=4,
        unreviewed_state=8,
        missing_group_metadata=2,
        incomplete_provenance=4,
        recent_import=3,
        stale_review_state=3,
    ),
    "quality": ReviewScoreWeights(
        low_mean_confidence=10,
        low_min_confidence=6,
        pending_proposals=6,
        rejection_rate=10,
        count_disagreement=12,
        unresolved_qc_severity=34,
        rare_class_presence=4,
        edited_acceptance_rate=8,
        unreviewed_state=10,
        missing_group_metadata=5,
        incomplete_provenance=12,
        recent_import=2,
        stale_review_state=8,
    ),
}


class ActiveLearningRoundService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.review_queues = ReviewQueueService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _round(self, round_id: str) -> ActiveLearningRound:
        round_record = self.session.get(ActiveLearningRound, round_id)
        if round_record is None:
            raise NotFoundError("Active-learning round not found")
        return round_record

    def _dataset_version(self, project_id: str, version_id: str | None) -> DatasetVersion | None:
        if version_id is None:
            return None
        version = self.session.get(DatasetVersion, version_id)
        if version is None or version.project_id != project_id:
            raise ValidationError("Dataset version must belong to the selected project")
        if version.status != "complete":
            raise ValidationError("Active learning requires a complete dataset version")
        return version

    def _model_ids(self, project_id: str, requested: list[str]) -> list[str]:
        model_ids = list(dict.fromkeys(requested))
        if not model_ids:
            return []
        models = list(
            self.session.scalars(
                select(ModelRegistration).where(ModelRegistration.id.in_(model_ids))
            )
        )
        if len(models) != len(model_ids) or any(model.project_id != project_id for model in models):
            raise ValidationError("All acquisition models must belong to the selected project")
        return model_ids

    def _selected_items(self, round_record: ActiveLearningRound) -> list[ReviewQueueItem]:
        item_ids = [
            str(item["queue_item_id"])
            for item in round_record.selection_manifest_json.get("items", [])
            if isinstance(item, dict) and item.get("queue_item_id")
        ]
        if not item_ids:
            return []
        items = list(
            self.session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.id.in_(item_ids)))
        )
        by_id = {item.id: item for item in items}
        return [by_id[item_id] for item_id in item_ids if item_id in by_id]

    def create_round(
        self,
        project_id: str,
        request: ActiveLearningRoundCreateRequest,
    ) -> ActiveLearningRoundResponse:
        self._project(project_id)
        version = self._dataset_version(project_id, request.dataset_version_id)
        model_ids = self._model_ids(project_id, request.model_ids)
        weights = _STRATEGY_WEIGHTS[request.strategy]
        queue_request = ReviewQueueCreateRequest(
            signal_weights=weights,
            created_by=request.created_by,
        )
        if version is None:
            queue = self.review_queues.create_queue_for_project(project_id, queue_request)
        else:
            queue = self.review_queues.create_queue_for_dataset_version(version.id, queue_request)

        queue_items = list(
            self.session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.review_queue_id == queue.id)
                .order_by(ReviewQueueItem.rank_position, ReviewQueueItem.image_id)
            )
        )
        if model_ids:
            model_filter = set(model_ids)
            queue_items = [
                item for item in queue_items if model_filter.intersection(item.model_ids_json)
            ]
        selected = queue_items[: request.requested_size]
        if not selected:
            raise ValidationError("The acquisition strategy did not select any review candidates")

        stable_items = [
            {
                "image_id": item.image_id,
                "rank_position": item.rank_position,
                "score": item.score,
                "input_checksum": item.input_checksum,
            }
            for item in selected
        ]
        identity_payload = {
            "schema_version": "active-learning-identity-0001",
            "project_id": project_id,
            "dataset_version_id": version.id if version else None,
            "strategy": request.strategy,
            "model_ids": model_ids,
            "requested_size": request.requested_size,
            "queue_formula_id": queue.formula_id,
            "queue_formula_version": queue.formula_version,
            "weights": weights.model_dump(mode="json"),
            "items": stable_items,
        }
        selection_sha256 = canonical_json_sha256(identity_payload)
        existing = self.session.scalar(
            select(ActiveLearningRound).where(
                ActiveLearningRound.project_id == project_id,
                ActiveLearningRound.selection_sha256 == selection_sha256,
            )
        )
        if existing is not None:
            generated_queue = self.session.get(ReviewQueue, queue.id)
            if generated_queue is not None:
                self.session.delete(generated_queue)
                self.session.commit()
            return ActiveLearningRoundResponse.model_validate(existing)

        manifest = {
            **identity_payload,
            "schema_version": "active-learning-0001",
            "review_queue_id": queue.id,
            "items": [
                {
                    **stable,
                    "queue_item_id": item.id,
                    "reason_summary": item.reason_summary,
                    "score_breakdown": item.score_breakdown_json,
                    "signal_values": item.signal_values_json,
                }
                for stable, item in zip(stable_items, selected, strict=True)
            ],
        }
        round_record = ActiveLearningRound(
            project_id=project_id,
            dataset_version_id=version.id if version else None,
            review_queue_id=queue.id,
            name=request.name.strip(),
            strategy=request.strategy,
            status="open",
            requested_size=request.requested_size,
            selected_count=len(selected),
            model_ids_json=model_ids,
            strategy_config_json={"weights": weights.model_dump(mode="json")},
            selection_manifest_json=manifest,
            selection_sha256=selection_sha256,
            feedback_summary_json={},
            created_by=request.created_by or "local_user",
        )
        self.session.add(round_record)
        self.session.commit()
        self.session.refresh(round_record)
        return ActiveLearningRoundResponse.model_validate(round_record)

    def list_rounds(self, project_id: str) -> list[ActiveLearningRoundResponse]:
        self._project(project_id)
        statement = (
            select(ActiveLearningRound)
            .where(ActiveLearningRound.project_id == project_id)
            .order_by(ActiveLearningRound.created_at.desc(), ActiveLearningRound.id)
        )
        return [
            ActiveLearningRoundResponse.model_validate(item)
            for item in self.session.scalars(statement)
        ]

    def get_round(self, round_id: str) -> ActiveLearningRoundResponse:
        return ActiveLearningRoundResponse.model_validate(self._round(round_id))

    def feedback(self, round_id: str) -> ActiveLearningFeedbackResponse:
        round_record = self._round(round_id)
        items = self._selected_items(round_record)
        state_counts = Counter(item.review_state for item in items)
        image_ids = [item.image_id for item in items]
        prediction_counts: Counter[str] = Counter()
        if image_ids:
            for status in self.session.scalars(
                select(PredictionProposal.review_status).where(
                    PredictionProposal.image_id.in_(image_ids)
                )
            ):
                prediction_counts[f"detection_{status}"] += 1
            for status in self.session.scalars(
                select(ClassificationPrediction.status).where(
                    ClassificationPrediction.image_id.in_(image_ids)
                )
            ):
                prediction_counts[f"classification_{status}"] += 1
        terminal = state_counts["completed"] + state_counts["skipped"]
        existing_summary = dict(round_record.feedback_summary_json or {})
        summary = {
            **existing_summary,
            "pending_count": state_counts["pending"],
            "in_progress_count": state_counts["in_progress"],
            "completed_count": state_counts["completed"],
            "skipped_count": state_counts["skipped"],
            "completion_fraction": terminal / max(round_record.selected_count, 1),
            "prediction_review_counts": dict(sorted(prediction_counts.items())),
        }
        round_record.feedback_summary_json = summary
        self.session.commit()
        return ActiveLearningFeedbackResponse(
            round_id=round_record.id,
            status=round_record.status,
            selected_count=round_record.selected_count,
            pending_count=state_counts["pending"],
            in_progress_count=state_counts["in_progress"],
            completed_count=state_counts["completed"],
            skipped_count=state_counts["skipped"],
            completion_fraction=terminal / max(round_record.selected_count, 1),
            prediction_review_counts=dict(sorted(prediction_counts.items())),
            feedback_dataset_version_id=summary.get("feedback_dataset_version_id"),
            feedback_manifest_sha256=summary.get("feedback_manifest_sha256"),
        )

    def _feedback_dataset(
        self,
        round_record: ActiveLearningRound,
        completed_items: list[ReviewQueueItem],
    ) -> DatasetVersion | None:
        if not completed_items:
            return None
        existing_id = dict(round_record.feedback_summary_json or {}).get(
            "feedback_dataset_version_id"
        )
        if isinstance(existing_id, str):
            existing = self.session.get(DatasetVersion, existing_id)
            if existing is not None and existing.project_id == round_record.project_id:
                return existing

        completed_image_ids = list(dict.fromkeys(item.image_id for item in completed_items))
        images = list(
            self.session.scalars(select(ImageAsset).where(ImageAsset.id.in_(completed_image_ids)))
        )
        images_by_id = {image.id: image for image in images}
        missing_ids = [image_id for image_id in completed_image_ids if image_id not in images_by_id]
        if missing_ids:
            raise ConflictError("One or more selected review images no longer exist")
        not_reviewed = [
            images_by_id[image_id].original_filename
            for image_id in completed_image_ids
            if images_by_id[image_id].annotation_status != "reviewed"
        ]
        if not_reviewed:
            examples = ", ".join(not_reviewed[:5])
            suffix = "" if len(not_reviewed) <= 5 else f" (+{len(not_reviewed) - 5} more)"
            raise ConflictError(
                "Completed active-learning items must be marked reviewed in the annotation "
                f"workspace before closing the round: {examples}{suffix}"
            )

        parent = self._dataset_version(round_record.project_id, round_record.dataset_version_id)
        requested_ratios = None
        if parent is not None and parent.requested_ratios_json:
            requested_ratios = SplitRatios.model_validate(parent.requested_ratios_json)
        dataset_request = DatasetVersionCreateRequest(
            name=f"{round_record.name[:160]} — feedback",
            notes=(
                "Immutable post-review dataset produced by active-learning round "
                f"{round_record.id}. Completed queue items were required to have reviewed "
                "image annotation status before inclusion."
            ),
            creator=round_record.created_by,
            parent_version_id=round_record.dataset_version_id,
            eligible_annotation_statuses=["reviewed"],
            split_method="group_random",
            requested_ratios=requested_ratios,
            split_seed=parent.split_seed if parent is not None else 0,
            reuse_parent_assignments=parent is not None,
        )
        created = MaskAwareDatasetVersionService(self.session, self.settings).create_version(
            round_record.project_id,
            dataset_request,
        )
        return self.session.get(DatasetVersion, created.id)

    def complete_round(self, round_id: str) -> ActiveLearningRoundResponse:
        round_record = self._round(round_id)
        if round_record.status == "complete":
            return ActiveLearningRoundResponse.model_validate(round_record)
        feedback = self.feedback(round_id)
        if feedback.pending_count or feedback.in_progress_count:
            raise ConflictError(
                "Complete or skip every selected review item before closing the round"
            )

        items = self._selected_items(round_record)
        completed_items = [item for item in items if item.review_state == "completed"]
        feedback_dataset = self._feedback_dataset(round_record, completed_items)
        summary = dict(round_record.feedback_summary_json or {})
        if feedback_dataset is not None:
            summary.update(
                {
                    "feedback_dataset_version_id": feedback_dataset.id,
                    "feedback_manifest_sha256": feedback_dataset.manifest_sha256,
                    "feedback_dataset_image_count": feedback_dataset.image_count,
                    "feedback_dataset_annotation_count": feedback_dataset.annotation_count,
                    "completed_image_ids": list(
                        dict.fromkeys(item.image_id for item in completed_items)
                    ),
                }
            )
        round_record.feedback_summary_json = summary
        round_record.status = "complete"
        round_record.completed_at = utc_now()
        self.session.commit()
        self.session.refresh(round_record)
        return ActiveLearningRoundResponse.model_validate(round_record)
