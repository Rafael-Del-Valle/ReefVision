"""Diversity-aware active-learning selection built on explainable review scores."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ReviewQueue, ReviewQueueItem
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.active_learning import ActiveLearningQueueCreateRequest
from reefvision.schemas.review_queues import (
    ReviewQueueCreateRequest,
    ReviewQueueResponse,
)
from reefvision.services.review_queues import ReviewQueueService
from reefvision.storage.datasets import canonical_json_sha256

ACTIVE_LEARNING_FORMULA_ID = "active_learning_diversity_v1"
ACTIVE_LEARNING_FORMULA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ActiveLearningCandidate:
    """One scored review item together with its image-level diversity metadata."""

    item: ReviewQueueItem
    image: ImageAsset

    @property
    def group_key(self) -> str | None:
        value = self.image.group_key
        return value.strip() if value is not None and value.strip() else None

    @property
    def group_bucket(self) -> str:
        return self.group_key or f"__ungrouped__:{self.image.id}"


@dataclass(frozen=True)
class ActiveLearningSelection:
    """A selected candidate and the deterministic score used to rank it."""

    candidate: ActiveLearningCandidate
    base_priority_score: float
    diversity_score: float
    selection_score: float


def _novel_fraction(values: Iterable[str], seen: set[str]) -> float | None:
    unique = {value for value in values if value}
    if not unique:
        return None
    return len(unique - seen) / len(unique)


def _candidate_diversity(
    candidate: ActiveLearningCandidate,
    *,
    seen_classes: set[str],
    seen_models: set[str],
    seen_groups: set[str],
    seen_splits: set[str],
    seen_severities: set[str],
) -> float:
    components: list[float] = []
    class_novelty = _novel_fraction(candidate.item.label_class_ids_json, seen_classes)
    model_novelty = _novel_fraction(candidate.item.model_ids_json, seen_models)
    if class_novelty is not None:
        components.append(class_novelty)
    if model_novelty is not None:
        components.append(model_novelty)
    if candidate.group_key is not None:
        components.append(0.0 if candidate.group_key in seen_groups else 1.0)
    if candidate.item.split:
        components.append(0.0 if candidate.item.split in seen_splits else 1.0)
    if candidate.item.highest_qc_severity:
        components.append(
            0.0 if candidate.item.highest_qc_severity in seen_severities else 1.0
        )
    return mean(components) if components else 0.0


def build_active_learning_score_breakdown(
    review_breakdown: Iterable[dict[str, Any]],
    *,
    diversity_score: float,
    diversity_weight: float,
) -> list[dict[str, Any]]:
    """Scale review contributions and append the diversity contribution."""

    priority_weight = 1.0 - diversity_weight
    scaled: list[dict[str, Any]] = []
    for component in review_breakdown:
        scaled.append(
            {
                **dict(component),
                "contribution": round(
                    float(component.get("contribution", 0.0)) * priority_weight,
                    2,
                ),
                "description": (
                    f"{component.get('description', '')} "
                    f"Scaled by the active-learning priority weight "
                    f"({priority_weight:.2f})."
                ).strip(),
            }
        )
    scaled.append(
        {
            "signal_id": "active_learning_diversity",
            "label": "Batch diversity",
            "raw_value": diversity_score,
            "normalized_value": diversity_score,
            "weight": diversity_weight,
            "contribution": round(diversity_score * diversity_weight * 100.0, 2),
            "description": (
                "Rewards candidates that add unseen classes, models, groups, "
                "splits, or QC severities to the selected batch."
            ),
        }
    )
    return scaled


def select_diverse_candidates(
    candidates: Iterable[ActiveLearningCandidate],
    *,
    max_items: int,
    diversity_weight: float,
    max_items_per_group: int | None,
) -> list[ActiveLearningSelection]:
    """Greedily select a deterministic uncertainty/diversity batch."""

    remaining = list(candidates)
    selected: list[ActiveLearningSelection] = []
    seen_classes: set[str] = set()
    seen_models: set[str] = set()
    seen_groups: set[str] = set()
    seen_splits: set[str] = set()
    seen_severities: set[str] = set()
    group_counts: Counter[str] = Counter()

    while remaining and len(selected) < max_items:
        scored: list[ActiveLearningSelection] = []
        for candidate in remaining:
            if (
                max_items_per_group is not None
                and group_counts[candidate.group_bucket] >= max_items_per_group
            ):
                continue
            diversity_score = _candidate_diversity(
                candidate,
                seen_classes=seen_classes,
                seen_models=seen_models,
                seen_groups=seen_groups,
                seen_splits=seen_splits,
                seen_severities=seen_severities,
            )
            base_priority = min(max(float(candidate.item.score), 0.0), 100.0)
            blended = 100.0 * (
                ((1.0 - diversity_weight) * (base_priority / 100.0))
                + (diversity_weight * diversity_score)
            )
            scored.append(
                ActiveLearningSelection(
                    candidate=candidate,
                    base_priority_score=round(base_priority, 2),
                    diversity_score=round(diversity_score, 6),
                    selection_score=round(blended, 2),
                )
            )
        if not scored:
            break
        choice = min(
            scored,
            key=lambda item: (
                -item.selection_score,
                -item.base_priority_score,
                -item.diversity_score,
                item.candidate.item.rank_position,
                item.candidate.item.image_id,
            ),
        )
        selected.append(choice)
        remaining = [
            candidate
            for candidate in remaining
            if candidate.item.id != choice.candidate.item.id
        ]
        candidate = choice.candidate
        seen_classes.update(candidate.item.label_class_ids_json)
        seen_models.update(candidate.item.model_ids_json)
        if candidate.group_key is not None:
            seen_groups.add(candidate.group_key)
        if candidate.item.split:
            seen_splits.add(candidate.item.split)
        if candidate.item.highest_qc_severity:
            seen_severities.add(candidate.item.highest_qc_severity)
        group_counts[candidate.group_bucket] += 1

    return selected


class ActiveLearningQueueService:
    """Create compact annotation batches from the existing review-priority signals."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.review_queues = ReviewQueueService(session, settings)

    def _base_request(
        self,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueCreateRequest:
        return ReviewQueueCreateRequest(
            source_quality_control_run_id=request.source_quality_control_run_id,
            signal_weights=request.signal_weights,
            created_by=request.created_by,
        )

    def create_for_project(
        self,
        project_id: str,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueResponse:
        base = self.review_queues.create_queue_for_project(
            project_id,
            self._base_request(request),
        )
        return self._finalize(base.id, request)

    def create_for_dataset_version(
        self,
        version_id: str,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueResponse:
        base = self.review_queues.create_queue_for_dataset_version(
            version_id,
            self._base_request(request),
        )
        return self._finalize(base.id, request)

    def regenerate(self, queue_id: str) -> ReviewQueueResponse:
        queue = self.session.get(ReviewQueue, queue_id)
        if queue is None:
            raise NotFoundError("Active-learning queue not found")
        if queue.formula_id != ACTIVE_LEARNING_FORMULA_ID:
            raise ValidationError(
                "Only active-learning queues use this regeneration endpoint"
            )
        active_config = queue.configuration_json.get("active_learning", {})
        request = ActiveLearningQueueCreateRequest(
            source_quality_control_run_id=queue.source_quality_control_run_id,
            signal_weights=queue.configuration_json.get("weights", {}),
            max_items=active_config.get("max_items", 100),
            min_priority_score=active_config.get("min_priority_score", 0.0),
            diversity_weight=active_config.get("diversity_weight", 0.35),
            max_items_per_group=active_config.get("max_items_per_group"),
            include_reviewed=active_config.get("include_reviewed", False),
            created_by=queue.created_by,
        )
        if queue.dataset_version_id is None:
            regenerated = self.create_for_project(queue.project_id, request)
        else:
            regenerated = self.create_for_dataset_version(
                queue.dataset_version_id,
                request,
            )
        regenerated_queue = self.session.get(ReviewQueue, regenerated.id)
        if regenerated_queue is None:
            raise NotFoundError("Regenerated active-learning queue was not created")
        regenerated_queue.regenerated_from_queue_id = queue.id
        self.session.commit()
        self.session.refresh(regenerated_queue)
        return ReviewQueueResponse.model_validate(regenerated_queue)

    def _finalize(
        self,
        queue_id: str,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueResponse:
        queue = self.session.get(ReviewQueue, queue_id)
        if queue is None:
            raise NotFoundError("Active-learning queue was not created")
        items = list(
            self.session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.review_queue_id == queue.id)
                .order_by(ReviewQueueItem.rank_position, ReviewQueueItem.image_id)
            )
        )
        image_ids = [item.image_id for item in items]
        images = {
            image.id: image
            for image in self.session.scalars(
                select(ImageAsset).where(ImageAsset.id.in_(image_ids))
            )
        }

        reviewed_excluded = 0
        below_threshold_excluded = 0
        candidates: list[ActiveLearningCandidate] = []
        for item in items:
            image = images.get(item.image_id)
            if image is None:
                continue
            is_reviewed = (
                float(
                    item.normalized_signals_json.get(
                        "unreviewed_state",
                        1.0,
                    )
                )
                <= 0.0
            )
            if is_reviewed and not request.include_reviewed:
                reviewed_excluded += 1
                continue
            if float(item.score) < request.min_priority_score:
                below_threshold_excluded += 1
                continue
            candidates.append(ActiveLearningCandidate(item=item, image=image))

        selections = select_diverse_candidates(
            candidates,
            max_items=request.max_items,
            diversity_weight=request.diversity_weight,
            max_items_per_group=request.max_items_per_group,
        )
        selected_ids = {selection.candidate.item.id for selection in selections}
        for item in items:
            if item.id not in selected_ids:
                self.session.delete(item)

        for rank, selection in enumerate(selections, start=1):
            item = selection.candidate.item
            item.rank_position = rank
            item.score = selection.selection_score
            item.signal_values_json = {
                **dict(item.signal_values_json),
                "active_learning_priority_score": selection.base_priority_score,
                "active_learning_diversity_score": selection.diversity_score,
                "active_learning_selection_score": selection.selection_score,
            }
            item.normalized_signals_json = {
                **dict(item.normalized_signals_json),
                "active_learning_priority": round(
                    selection.base_priority_score / 100.0,
                    6,
                ),
                "active_learning_diversity": selection.diversity_score,
            }
            item.weights_json = {
                **dict(item.weights_json),
                "active_learning_diversity": request.diversity_weight,
            }
            item.score_breakdown_json = build_active_learning_score_breakdown(
                item.score_breakdown_json,
                diversity_score=selection.diversity_score,
                diversity_weight=request.diversity_weight,
            )
            selection_reason = (
                f"Active-learning score {selection.selection_score:.2f}: priority "
                f"{selection.base_priority_score:.2f}, diversity "
                f"{selection.diversity_score:.2f}."
            )
            item.reason_summary = (
                f"{selection_reason} {item.reason_summary}"
                if item.reason_summary
                else selection_reason
            )
            item.input_checksum = canonical_json_sha256(
                {
                    "source_item_checksum": item.input_checksum,
                    "rank_position": rank,
                    "priority_score": selection.base_priority_score,
                    "diversity_score": selection.diversity_score,
                    "selection_score": selection.selection_score,
                }
            )

        queue.formula_id = ACTIVE_LEARNING_FORMULA_ID
        queue.formula_version = ACTIVE_LEARNING_FORMULA_VERSION
        queue.item_count = len(selections)
        queue.configuration_json = {
            **dict(queue.configuration_json),
            "active_learning": {
                "max_items": request.max_items,
                "min_priority_score": request.min_priority_score,
                "diversity_weight": request.diversity_weight,
                "max_items_per_group": request.max_items_per_group,
                "include_reviewed": request.include_reviewed,
            },
        }
        queue.input_checksums_json = {
            **dict(queue.input_checksums_json),
            "active_learning_selection_sha256": canonical_json_sha256(
                [
                    {
                        "image_id": selection.candidate.item.image_id,
                        "rank": rank,
                        "priority": selection.base_priority_score,
                        "diversity": selection.diversity_score,
                        "selection": selection.selection_score,
                    }
                    for rank, selection in enumerate(selections, start=1)
                ]
            ),
            "active_learning_candidate_count": len(candidates),
        }
        queue.summary_json = {
            **dict(queue.summary_json),
            "candidate_count": len(candidates),
            "selected_count": len(selections),
            "reviewed_excluded": reviewed_excluded,
            "below_threshold_excluded": below_threshold_excluded,
            "average_selection_score": (
                round(
                    mean(selection.selection_score for selection in selections),
                    2,
                )
                if selections
                else 0.0
            ),
            "average_diversity_score": (
                round(
                    mean(selection.diversity_score for selection in selections),
                    4,
                )
                if selections
                else 0.0
            ),
            "top_image_ids": [
                selection.candidate.item.image_id for selection in selections[:10]
            ],
            "counts_by_group": dict(
                Counter(
                    selection.candidate.group_key or "ungrouped"
                    for selection in selections
                )
            ),
        }
        self.session.commit()
        self.session.refresh(queue)
        return ReviewQueueResponse.model_validate(queue)
