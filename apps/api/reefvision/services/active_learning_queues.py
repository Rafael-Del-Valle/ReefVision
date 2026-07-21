"""Diversity-aware active-learning selection built on explainable review scores."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ActiveLearningCycle,
    Annotation,
    ClassificationPrediction,
    DatasetVersion,
    ImageAsset,
    ImageEmbedding,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.active_learning_selection import (
    SelectionCandidate,
    SelectionResult,
    entropy,
    least_confidence,
    margin_uncertainty,
    select_candidates,
)
from reefvision.schemas.active_learning import (
    ActiveLearningQueueCreateRequest,
    ActiveLearningQueuePromotionRequest,
    ActiveLearningQueuePromotionResponse,
)
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleCreateRequest,
    ActiveLearningSelectionRecordRequest,
)
from reefvision.schemas.dataset_versions import DatasetVersionCreateRequest
from reefvision.schemas.review_queues import (
    ReviewQueueCreateRequest,
    ReviewQueueResponse,
)
from reefvision.services.active_learning_cycles import ActiveLearningCycleService
from reefvision.services.measurement_aware_dataset_versions import (
    MeasurementAwareDatasetVersionService,
)
from reefvision.services.review_queues import ReviewQueueService
from reefvision.storage.datasets import canonical_json_sha256

ACTIVE_LEARNING_FORMULA_ID = "active_learning_diversity_v1"
ACTIVE_LEARNING_FORMULA_VERSION = "2.0.0"


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


@dataclass(frozen=True)
class PersistedEmbeddingCandidate:
    """One queue candidate joined to immutable embedding and prediction inputs."""

    candidate: ActiveLearningCandidate
    embedding: ImageEmbedding | None
    probabilities: tuple[float, ...]
    fragment_key: str | None
    manual_priority: bool

    @property
    def vector(self) -> tuple[float, ...] | None:
        if self.embedding is None:
            return None
        return tuple(float(value) for value in self.embedding.vector_json)


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
        components.append(0.0 if candidate.item.highest_qc_severity in seen_severities else 1.0)
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
            candidate for candidate in remaining if candidate.item.id != choice.candidate.item.id
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


def _cosine_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if len(first) != len(second):
        raise ValidationError("Active-learning embeddings use inconsistent dimensions")
    value = sum(left * right for left, right in zip(first, second, strict=True))
    return max(-1.0, min(1.0, value))


def _selection_reason_labels(
    result: SelectionResult,
    *,
    has_classes: bool,
) -> list[str]:
    reasons: list[str] = []
    if result.manual_priority:
        reasons.append("Manual priority")
    if result.uncertainty >= 0.5:
        reasons.append("High uncertainty")
    if result.diversity >= 0.5:
        reasons.append("High novelty")
    if result.class_balance >= 0.5:
        reasons.append("Rare class" if has_classes else "Missing class")
    if result.cluster_id is not None or result.diversity > 0:
        reasons.append("Diversity representative")
    if len(reasons) > 1:
        reasons.append("Combination score")
    return reasons or ["Combination score"]


def _enhanced_score_breakdown(
    result: SelectionResult,
    *,
    base_score: float,
    uncertainty_weight: float,
    novelty_weight: float,
    density_weight: float,
    base_priority_weight: float,
    class_balance_weight: float,
) -> tuple[list[dict[str, Any]], float]:
    weighted = [
        (
            "active_learning_uncertainty",
            "Prediction uncertainty",
            result.uncertainty,
            uncertainty_weight,
            "Entropy, confidence margin, or least-confidence signal from persisted predictions.",
        ),
        (
            "active_learning_novelty",
            "Cosine novelty",
            min(max(result.diversity, 0.0), 1.0),
            novelty_weight,
            "Distance from the nearest already-selected persisted image embedding.",
        ),
        (
            "active_learning_density",
            "Embedding density",
            result.density,
            density_weight,
            "Preference for a representative sample from a populated embedding region.",
        ),
        (
            "active_learning_priority",
            "Existing review priority",
            min(max(base_score / 100.0, 0.0), 1.0),
            base_priority_weight,
            "Existing review signals such as pending proposals, confidence, and QC state.",
        ),
        (
            "active_learning_class_balance",
            "Class balance",
            result.class_balance,
            class_balance_weight,
            "Rewards rare, not-yet-represented, or currently missing classes.",
        ),
    ]
    total_weight = sum(weight for _id, _label, _value, weight, _description in weighted)
    if total_weight <= 0:
        raise ValidationError("At least one active-learning score weight must be positive")
    breakdown: list[dict[str, Any]] = []
    score = 0.0
    for signal_id, label, value, weight, description in weighted:
        contribution = value * (weight / total_weight) * 100.0
        score += contribution
        breakdown.append(
            {
                "signal_id": signal_id,
                "label": label,
                "raw_value": round(value, 6),
                "normalized_value": round(value, 6),
                "weight": weight,
                "contribution": round(contribution, 2),
                "description": description,
            }
        )
    return breakdown, round(score, 2)


class ActiveLearningQueueService:
    """Create compact annotation batches from the existing review-priority signals."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.review_queues = ReviewQueueService(session, settings)

    def _generation_key(
        self,
        *,
        project_id: str,
        dataset_version_id: str | None,
        request: ActiveLearningQueueCreateRequest,
        regeneration_token: str | None = None,
    ) -> str:
        images = list(
            self.session.scalars(
                select(ImageAsset)
                .where(ImageAsset.project_id == project_id)
                .order_by(ImageAsset.id)
            )
        )
        image_ids = [image.id for image in images]
        proposals = list(
            self.session.scalars(
                select(PredictionProposal)
                .where(
                    PredictionProposal.project_id == project_id,
                    PredictionProposal.image_id.in_(image_ids),
                )
                .order_by(PredictionProposal.id)
            )
        )
        classifications = list(
            self.session.scalars(
                select(ClassificationPrediction)
                .where(
                    ClassificationPrediction.project_id == project_id,
                    ClassificationPrediction.image_id.in_(image_ids),
                )
                .order_by(ClassificationPrediction.id)
            )
        )
        embeddings = list(
            self.session.scalars(
                select(ImageEmbedding)
                .where(
                    ImageEmbedding.project_id == project_id,
                    ImageEmbedding.source_kind == "image",
                )
                .order_by(ImageEmbedding.id)
            )
        )
        return canonical_json_sha256(
            {
                "scope": {
                    "project_id": project_id,
                    "dataset_version_id": dataset_version_id,
                },
                "request": request.model_dump(mode="json"),
                "regeneration_token": regeneration_token,
                "images": [
                    {
                        "id": item.id,
                        "sha256": item.sha256,
                        "annotation_revision": item.annotation_revision,
                        "annotation_status": item.annotation_status,
                        "group_key": item.group_key,
                        "metadata": item.metadata_json,
                    }
                    for item in images
                ],
                "predictions": [
                    {
                        "id": item.id,
                        "image_id": item.image_id,
                        "model_id": item.model_id,
                        "confidence": item.confidence,
                        "label_class_id": item.label_class_id,
                        "review_status": item.review_status,
                    }
                    for item in proposals
                ],
                "classifications": [
                    {
                        "id": item.id,
                        "image_id": item.image_id,
                        "model_id": item.model_id,
                        "probabilities": item.probabilities_json,
                        "review_status": item.review_status,
                    }
                    for item in classifications
                ],
                "embeddings": [
                    {
                        "image_id": item.image_id,
                        "provider_id": item.provider_id,
                        "model_id": item.embedding_model_id,
                        "model_checksum": item.embedding_model_checksum,
                        "preprocessing_version": item.preprocessing_version,
                        "source_image_sha256": item.source_image_sha256,
                        "vector_sha256": item.vector_sha256,
                        "status": item.status,
                    }
                    for item in embeddings
                ],
            }
        )

    def _existing_generation(self, generation_key: str) -> ReviewQueueResponse | None:
        queue = self.session.scalar(
            select(ReviewQueue).where(ReviewQueue.generation_key == generation_key)
        )
        return ReviewQueueResponse.model_validate(queue) if queue is not None else None

    def _next_revision(self, project_id: str) -> int:
        value = self.session.scalar(
            select(func.max(ReviewQueue.revision)).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.formula_id == ACTIVE_LEARNING_FORMULA_ID,
            )
        )
        return int(value or 0) + 1

    def _base_request(
        self,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueCreateRequest:
        return ReviewQueueCreateRequest(
            source_quality_control_run_id=request.source_quality_control_run_id,
            signal_weights=request.signal_weights,
            created_by=request.created_by,
        )

    def _validate_request_scope(
        self,
        project_id: str,
        request: ActiveLearningQueueCreateRequest,
    ) -> None:
        if request.source_model_id:
            source_model = self.session.get(ModelRegistration, request.source_model_id)
            if source_model is None or source_model.project_id != project_id:
                raise ValidationError("Source model must belong to the selected project")
        requested_ids = set(request.manual_include_image_ids) | set(
            request.manual_exclude_image_ids
        )
        if requested_ids:
            found_ids = set(
                self.session.scalars(
                    select(ImageAsset.id).where(
                        ImageAsset.project_id == project_id,
                        ImageAsset.id.in_(requested_ids),
                    )
                )
            )
            if found_ids != requested_ids:
                raise ValidationError(
                    "Every manually included or excluded image must belong to the project"
                )

    def _prediction_probabilities(
        self,
        project_id: str,
        image_ids: list[str],
        source_model_id: str | None,
    ) -> dict[str, tuple[float, ...]]:
        classification_query = select(ClassificationPrediction).where(
            ClassificationPrediction.project_id == project_id,
            ClassificationPrediction.image_id.in_(image_ids),
            ClassificationPrediction.review_status == "pending",
        )
        proposal_query = select(PredictionProposal).where(
            PredictionProposal.project_id == project_id,
            PredictionProposal.image_id.in_(image_ids),
            PredictionProposal.review_status == "pending",
        )
        if source_model_id:
            classification_query = classification_query.where(
                ClassificationPrediction.model_id == source_model_id
            )
            proposal_query = proposal_query.where(PredictionProposal.model_id == source_model_id)
        classifications = list(self.session.scalars(classification_query))
        proposals = list(self.session.scalars(proposal_query))
        classification_by_image: dict[str, list[ClassificationPrediction]] = {}
        for prediction in classifications:
            classification_by_image.setdefault(prediction.image_id, []).append(prediction)
        proposals_by_image: dict[str, list[PredictionProposal]] = {}
        for proposal in proposals:
            proposals_by_image.setdefault(proposal.image_id, []).append(proposal)

        probabilities: dict[str, tuple[float, ...]] = {}
        for image_id in image_ids:
            classification_items = classification_by_image.get(image_id, [])
            totals: dict[str, float] = {}
            for prediction in classification_items:
                for label, value in dict(prediction.probabilities_json or {}).items():
                    numeric = float(value)
                    if isfinite(numeric) and numeric >= 0:
                        totals[label] = totals.get(label, 0.0) + numeric
            total = sum(totals.values())
            if total > 0:
                probabilities[image_id] = tuple(totals[label] / total for label in sorted(totals))
                continue
            confidence_values = [
                min(max(float(item.confidence), 0.0), 1.0)
                for item in proposals_by_image.get(image_id, [])
                if isfinite(float(item.confidence))
            ]
            if confidence_values:
                confidence = mean(confidence_values)
                probabilities[image_id] = (confidence, 1.0 - confidence)
        return probabilities

    def _matching_embeddings(
        self,
        project_id: str,
        images: dict[str, ImageAsset],
        request: ActiveLearningQueueCreateRequest,
    ) -> tuple[dict[str, ImageEmbedding], dict[str, Any], int, int]:
        if request.embedding_model_id is None or request.embedding_provider_id is None:
            return {}, {}, 0, 0
        query = select(ImageEmbedding).where(
            ImageEmbedding.project_id == project_id,
            ImageEmbedding.provider_id == request.embedding_provider_id,
            ImageEmbedding.embedding_model_id == request.embedding_model_id,
            ImageEmbedding.source_kind == "image",
        )
        if request.embedding_model_checksum is not None:
            query = query.where(
                ImageEmbedding.embedding_model_checksum == request.embedding_model_checksum
            )
        if request.embedding_preprocessing_version is not None:
            query = query.where(
                ImageEmbedding.preprocessing_version == request.embedding_preprocessing_version
            )
        rows = list(self.session.scalars(query.order_by(ImageEmbedding.updated_at.desc())))
        configuration_keys = {
            (
                item.embedding_model_checksum,
                item.model_version,
                item.preprocessing_version,
                item.dimension,
            )
            for item in rows
            if item.status == "ready"
            and item.image_id in images
            and item.source_image_sha256 == images[item.image_id].sha256
        }
        if len(configuration_keys) > 1:
            raise ValidationError(
                "Multiple embedding versions match this queue. Select an exact model checksum "
                "and preprocessing version."
            )
        resolved_configuration: dict[str, Any] = {}
        if configuration_keys:
            checksum, model_version, preprocessing_version, dimension = next(
                iter(configuration_keys)
            )
            resolved_configuration = {
                "provider_id": request.embedding_provider_id,
                "model_id": request.embedding_model_id,
                "model_checksum": checksum,
                "model_version": model_version,
                "preprocessing_version": preprocessing_version,
                "dimension": dimension,
            }
        by_image: dict[str, ImageEmbedding] = {}
        stale_count = 0
        for row in rows:
            image = images.get(row.image_id)
            if image is None or row.image_id in by_image:
                continue
            if row.status != "ready" or row.source_image_sha256 != image.sha256:
                stale_count += 1
                continue
            by_image[row.image_id] = row
        missing_count = sum(image_id not in by_image for image_id in images)
        return by_image, resolved_configuration, missing_count, stale_count

    def _prepare_persisted_candidates(
        self,
        candidates: list[ActiveLearningCandidate],
        request: ActiveLearningQueueCreateRequest,
    ) -> tuple[list[PersistedEmbeddingCandidate], dict[str, Any]]:
        images = {candidate.image.id: candidate.image for candidate in candidates}
        embeddings, embedding_config, missing_count, stale_count = self._matching_embeddings(
            candidates[0].image.project_id if candidates else "",
            images,
            request,
        )
        probabilities = self._prediction_probabilities(
            candidates[0].image.project_id if candidates else "",
            list(images),
            request.source_model_id,
        )
        manual_includes = set(request.manual_include_image_ids)
        manual_excludes = set(request.manual_exclude_image_ids)
        prepared: list[PersistedEmbeddingCandidate] = []
        excluded_manual = 0
        excluded_missing_embedding = 0
        for candidate in candidates:
            if candidate.image.id in manual_excludes:
                excluded_manual += 1
                continue
            embedding = embeddings.get(candidate.image.id)
            manual_priority = candidate.image.id in manual_includes
            if request.embedding_model_id and embedding is None and not manual_priority:
                excluded_missing_embedding += 1
                continue
            fragment_value = dict(candidate.image.metadata_json or {}).get(
                request.fragment_metadata_key
            )
            fragment_key = (
                str(fragment_value).strip()
                if fragment_value is not None and str(fragment_value).strip()
                else None
            )
            prepared.append(
                PersistedEmbeddingCandidate(
                    candidate=candidate,
                    embedding=embedding,
                    probabilities=probabilities.get(candidate.image.id, ()),
                    fragment_key=fragment_key,
                    manual_priority=manual_priority,
                )
            )

        prepared.sort(
            key=lambda item: (
                not item.manual_priority,
                -float(item.candidate.item.score),
                item.candidate.image.id,
            )
        )
        retained: list[PersistedEmbeddingCandidate] = []
        vector_checksums: dict[str, str] = {}
        duplicate_count = 0
        near_duplicate_count = 0
        for item in prepared:
            embedding = item.embedding
            if embedding is None or item.manual_priority:
                retained.append(item)
                if embedding is not None:
                    vector_checksums.setdefault(embedding.vector_sha256, item.candidate.image.id)
                continue
            if request.suppress_exact_duplicates and embedding.vector_sha256 in vector_checksums:
                duplicate_count += 1
                continue
            nearest: tuple[float, str] | None = None
            if request.suppress_near_duplicates and item.vector is not None:
                for existing in retained:
                    if existing.vector is None:
                        continue
                    similarity = _cosine_similarity(item.vector, existing.vector)
                    if nearest is None or similarity > nearest[0]:
                        nearest = (similarity, existing.candidate.image.id)
                if nearest and nearest[0] >= request.near_duplicate_cosine_similarity:
                    near_duplicate_count += 1
                    continue
            retained.append(item)
            vector_checksums[embedding.vector_sha256] = item.candidate.image.id

        return retained, {
            "embedding_configuration": embedding_config,
            "missing_embedding_count": missing_count,
            "stale_embedding_count": stale_count,
            "excluded_missing_embedding_count": excluded_missing_embedding,
            "manual_excluded_count": excluded_manual,
            "exact_duplicate_suppressed_count": duplicate_count,
            "near_duplicate_suppressed_count": near_duplicate_count,
        }

    def _select_persisted_candidates(
        self,
        candidates: list[ActiveLearningCandidate],
        request: ActiveLearningQueueCreateRequest,
    ) -> tuple[
        list[tuple[PersistedEmbeddingCandidate, SelectionResult]],
        dict[str, Any],
    ]:
        prepared, summary = self._prepare_persisted_candidates(candidates, request)
        selection_inputs = [
            SelectionCandidate(
                candidate_id=item.candidate.item.id,
                embedding=item.vector,
                probabilities=item.probabilities,
                base_score=float(item.candidate.item.score),
                group_id=item.candidate.group_key,
                fragment_id=item.fragment_key,
                class_ids=tuple(item.candidate.item.label_class_ids_json),
                manual_priority=item.manual_priority,
                metadata={"image_id": item.candidate.image.id},
            )
            for item in prepared
        ]
        novelty_weight = (
            request.novelty_weight
            if request.novelty_weight is not None
            else request.diversity_weight
        )
        selected = select_candidates(
            selection_inputs,
            budget=request.max_items,
            strategy=request.selection_strategy,
            seed=0,
            group_limit=request.max_items_per_group,
            fragment_limit=request.max_items_per_fragment,
            uncertainty_weight=request.uncertainty_weight,
            diversity_weight=novelty_weight,
            density_weight=request.density_weight,
            disagreement_weight=0.0,
            base_score_weight=request.base_priority_weight,
            class_balance_weight=0.1 if request.class_balancing else 0.0,
        )
        by_id = {item.candidate.item.id: item for item in prepared}
        return [(by_id[result.candidate_id], result) for result in selected], summary

    def _create_cycle_for_queue(
        self,
        queue: ReviewQueue,
        request: ActiveLearningQueueCreateRequest,
    ) -> ActiveLearningCycle:
        cycle_service = ActiveLearningCycleService(self.session)
        cycle_response = cycle_service.create(
            queue.project_id,
            ActiveLearningCycleCreateRequest(
                name=request.cycle_name or f"Active learning queue revision {queue.revision}",
                selection_strategy=request.selection_strategy,
                annotation_budget=max(queue.item_count, 1),
                source_model_id=request.source_model_id,
                selection_config=dict(queue.configuration_json.get("active_learning", {})),
                notes=(
                    "Software-assisted image selection only; this cycle does not establish "
                    "scientific model validity."
                ),
            ),
        )
        item_image_ids = list(
            self.session.scalars(
                select(ReviewQueueItem.image_id)
                .where(ReviewQueueItem.review_queue_id == queue.id)
                .order_by(ReviewQueueItem.rank_position)
            )
        )
        cycle_service.record_selection(
            cycle_response.id,
            ActiveLearningSelectionRecordRequest(
                review_queue_id=queue.id,
                selected_candidate_ids=item_image_ids,
                selection_result={
                    "queue_revision": queue.revision,
                    "generation_key": queue.generation_key,
                    "selection_sha256": queue.input_checksums_json.get(
                        "active_learning_selection_sha256"
                    ),
                },
            ),
        )
        cycle = self.session.get(ActiveLearningCycle, cycle_response.id)
        if cycle is None:
            raise NotFoundError("Active-learning cycle was not persisted")
        active_config = dict(queue.configuration_json.get("active_learning", {}))
        embedding_config = dict(queue.summary_json.get("embedding_configuration", {}))
        cycle.embedding_provider_id = active_config.get("embedding_provider_id")
        cycle.embedding_model_id = active_config.get("embedding_model_id")
        cycle.embedding_model_checksum = embedding_config.get(
            "model_checksum"
        ) or active_config.get("embedding_model_checksum")
        cycle.queue_revision = queue.revision
        cycle.warnings_json = list(queue.summary_json.get("warnings", []))
        queue.summary_json = {**dict(queue.summary_json), "cycle_id": cycle.id}
        self.session.commit()
        self.session.refresh(cycle)
        return cycle

    def create_for_project(
        self,
        project_id: str,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueResponse:
        self._validate_request_scope(project_id, request)
        generation_key = self._generation_key(
            project_id=project_id,
            dataset_version_id=None,
            request=request,
        )
        existing = self._existing_generation(generation_key)
        if existing is not None:
            return existing
        base = self.review_queues.create_queue_for_project(
            project_id,
            self._base_request(request),
        )
        return self._finalize(base.id, request, generation_key=generation_key)

    def create_for_dataset_version(
        self,
        version_id: str,
        request: ActiveLearningQueueCreateRequest,
    ) -> ReviewQueueResponse:
        version = self.session.get(DatasetVersion, version_id)
        if version is None:
            raise NotFoundError("Dataset version not found")
        self._validate_request_scope(version.project_id, request)
        generation_key = self._generation_key(
            project_id=version.project_id,
            dataset_version_id=version.id,
            request=request,
        )
        existing = self._existing_generation(generation_key)
        if existing is not None:
            return existing
        base = self.review_queues.create_queue_for_dataset_version(
            version_id,
            self._base_request(request),
        )
        return self._finalize(base.id, request, generation_key=generation_key)

    def regenerate(self, queue_id: str) -> ReviewQueueResponse:
        queue = self.session.get(ReviewQueue, queue_id)
        if queue is None:
            raise NotFoundError("Active-learning queue not found")
        if queue.formula_id != ACTIVE_LEARNING_FORMULA_ID:
            raise ValidationError("Only active-learning queues use this regeneration endpoint")
        active_config = queue.configuration_json.get("active_learning", {})
        request = ActiveLearningQueueCreateRequest(
            source_quality_control_run_id=queue.source_quality_control_run_id,
            signal_weights=queue.configuration_json.get("weights", {}),
            max_items=active_config.get("max_items", 100),
            min_priority_score=active_config.get("min_priority_score", 0.0),
            diversity_weight=active_config.get("diversity_weight", 0.35),
            max_items_per_group=active_config.get("max_items_per_group"),
            max_items_per_fragment=active_config.get("max_items_per_fragment"),
            include_reviewed=active_config.get("include_reviewed", False),
            selection_strategy=active_config.get("selection_strategy", "k_center"),
            uncertainty_weight=active_config.get("uncertainty_weight", 0.45),
            novelty_weight=active_config.get("novelty_weight"),
            base_priority_weight=active_config.get("base_priority_weight", 0.1),
            density_weight=active_config.get("density_weight", 0.0),
            embedding_provider_id=active_config.get("embedding_provider_id"),
            embedding_model_id=active_config.get("embedding_model_id"),
            embedding_model_checksum=active_config.get("embedding_model_checksum"),
            embedding_preprocessing_version=active_config.get("embedding_preprocessing_version"),
            source_model_id=active_config.get("source_model_id"),
            class_balancing=active_config.get("class_balancing", True),
            suppress_exact_duplicates=active_config.get("suppress_exact_duplicates", True),
            suppress_near_duplicates=active_config.get("suppress_near_duplicates", True),
            near_duplicate_cosine_similarity=active_config.get(
                "near_duplicate_cosine_similarity", 0.995
            ),
            fragment_metadata_key=active_config.get("fragment_metadata_key", "fragment_id"),
            manual_include_image_ids=active_config.get("manual_include_image_ids", []),
            manual_exclude_image_ids=active_config.get("manual_exclude_image_ids", []),
            create_cycle=active_config.get("create_cycle", True),
            cycle_name=active_config.get("cycle_name"),
            created_by=queue.created_by,
        )
        self._validate_request_scope(queue.project_id, request)
        generation_key = self._generation_key(
            project_id=queue.project_id,
            dataset_version_id=queue.dataset_version_id,
            request=request,
            regeneration_token=f"queue:{queue.id}:revision:{queue.revision + 1}",
        )
        existing = self._existing_generation(generation_key)
        if existing is not None:
            return existing
        if queue.dataset_version_id is None:
            base = self.review_queues.create_queue_for_project(
                queue.project_id, self._base_request(request)
            )
        else:
            base = self.review_queues.create_queue_for_dataset_version(
                queue.dataset_version_id, self._base_request(request)
            )
        regenerated = self._finalize(
            base.id,
            request,
            generation_key=generation_key,
            regenerated_from_queue_id=queue.id,
        )
        regenerated_queue = self.session.get(ReviewQueue, regenerated.id)
        if regenerated_queue is None:
            raise NotFoundError("Regenerated active-learning queue was not created")
        return ReviewQueueResponse.model_validate(regenerated_queue)

    def _finalize(
        self,
        queue_id: str,
        request: ActiveLearningQueueCreateRequest,
        *,
        generation_key: str,
        regenerated_from_queue_id: str | None = None,
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
            manually_included = item.image_id in request.manual_include_image_ids
            is_reviewed = (
                float(
                    item.normalized_signals_json.get(
                        "unreviewed_state",
                        1.0,
                    )
                )
                <= 0.0
            )
            if is_reviewed and not request.include_reviewed and not manually_included:
                reviewed_excluded += 1
                continue
            if float(item.score) < request.min_priority_score and not manually_included:
                below_threshold_excluded += 1
                continue
            candidates.append(ActiveLearningCandidate(item=item, image=image))

        selections, selection_summary = self._select_persisted_candidates(candidates, request)
        selected_ids = {selection.candidate.item.id for selection, _result in selections}
        for item in items:
            if item.id not in selected_ids:
                self.session.delete(item)

        novelty_weight = (
            request.novelty_weight
            if request.novelty_weight is not None
            else request.diversity_weight
        )
        selection_checksums: list[dict[str, Any]] = []
        for rank, (selection, result) in enumerate(selections, start=1):
            item = selection.candidate.item
            original_priority = float(item.score)
            breakdown, score = _enhanced_score_breakdown(
                result,
                base_score=original_priority,
                uncertainty_weight=request.uncertainty_weight,
                novelty_weight=novelty_weight,
                density_weight=request.density_weight,
                base_priority_weight=request.base_priority_weight,
                class_balance_weight=0.1 if request.class_balancing else 0.0,
            )
            reasons = _selection_reason_labels(
                result,
                has_classes=bool(item.label_class_ids_json),
            )
            item.rank_position = rank
            item.score = score
            item.selection_reasons_json = reasons
            item.manual_state = "included" if selection.manual_priority else "automatic"
            item.fragment_key = selection.fragment_key
            item.near_duplicate_key = (
                selection.embedding.vector_sha256 if selection.embedding is not None else None
            )
            item.signal_values_json = {
                **dict(item.signal_values_json),
                "active_learning_priority_score": original_priority,
                "active_learning_uncertainty_score": result.uncertainty,
                "active_learning_entropy": entropy(selection.probabilities),
                "active_learning_margin_uncertainty": margin_uncertainty(selection.probabilities),
                "active_learning_least_confidence": least_confidence(selection.probabilities),
                "active_learning_novelty_score": result.diversity,
                "active_learning_density_score": result.density,
                "active_learning_class_balance_score": result.class_balance,
                "active_learning_selection_score": score,
            }
            item.normalized_signals_json = {
                **dict(item.normalized_signals_json),
                "active_learning_priority": round(
                    original_priority / 100.0,
                    6,
                ),
                "active_learning_uncertainty": round(result.uncertainty, 6),
                "active_learning_novelty": round(result.diversity, 6),
                "active_learning_diversity": round(result.diversity, 6),
                "active_learning_density": round(result.density, 6),
                "active_learning_class_balance": round(result.class_balance, 6),
            }
            item.weights_json = {
                **dict(item.weights_json),
                "active_learning_uncertainty": request.uncertainty_weight,
                "active_learning_novelty": novelty_weight,
                "active_learning_diversity": novelty_weight,
                "active_learning_density": request.density_weight,
                "active_learning_priority": request.base_priority_weight,
                "active_learning_class_balance": 0.1 if request.class_balancing else 0.0,
            }
            item.score_breakdown_json = breakdown
            selection_reason = f"Active-learning score {score:.2f}: {', '.join(reasons)}."
            item.reason_summary = (
                f"{selection_reason} {item.reason_summary}"
                if item.reason_summary
                else selection_reason
            )
            item.input_checksum = canonical_json_sha256(
                {
                    "source_item_checksum": item.input_checksum,
                    "rank_position": rank,
                    "priority_score": original_priority,
                    "uncertainty_score": result.uncertainty,
                    "novelty_score": result.diversity,
                    "selection_score": score,
                    "embedding_vector_sha256": (
                        selection.embedding.vector_sha256
                        if selection.embedding is not None
                        else None
                    ),
                }
            )
            selection_checksums.append(
                {
                    "image_id": item.image_id,
                    "rank": rank,
                    "priority": original_priority,
                    "uncertainty": result.uncertainty,
                    "novelty": result.diversity,
                    "selection": score,
                    "embedding_vector_sha256": (
                        selection.embedding.vector_sha256
                        if selection.embedding is not None
                        else None
                    ),
                }
            )

        queue.formula_id = ACTIVE_LEARNING_FORMULA_ID
        queue.formula_version = ACTIVE_LEARNING_FORMULA_VERSION
        queue.revision = self._next_revision(queue.project_id)
        queue.generation_key = generation_key
        queue.regenerated_from_queue_id = regenerated_from_queue_id
        queue.item_count = len(selections)
        queue.configuration_json = {
            **dict(queue.configuration_json),
            "active_learning": {
                "max_items": request.max_items,
                "min_priority_score": request.min_priority_score,
                "diversity_weight": request.diversity_weight,
                "novelty_weight": request.novelty_weight,
                "uncertainty_weight": request.uncertainty_weight,
                "base_priority_weight": request.base_priority_weight,
                "density_weight": request.density_weight,
                "max_items_per_group": request.max_items_per_group,
                "max_items_per_fragment": request.max_items_per_fragment,
                "include_reviewed": request.include_reviewed,
                "selection_strategy": request.selection_strategy,
                "embedding_provider_id": request.embedding_provider_id,
                "embedding_model_id": request.embedding_model_id,
                "embedding_model_checksum": request.embedding_model_checksum,
                "embedding_preprocessing_version": (request.embedding_preprocessing_version),
                "source_model_id": request.source_model_id,
                "class_balancing": request.class_balancing,
                "suppress_exact_duplicates": request.suppress_exact_duplicates,
                "suppress_near_duplicates": request.suppress_near_duplicates,
                "near_duplicate_cosine_similarity": (request.near_duplicate_cosine_similarity),
                "fragment_metadata_key": request.fragment_metadata_key,
                "manual_include_image_ids": request.manual_include_image_ids,
                "manual_exclude_image_ids": request.manual_exclude_image_ids,
                "create_cycle": request.create_cycle,
                "cycle_name": request.cycle_name,
            },
        }
        queue.input_checksums_json = {
            **dict(queue.input_checksums_json),
            "active_learning_selection_sha256": canonical_json_sha256(selection_checksums),
            "active_learning_candidate_count": len(candidates),
            "generation_key": generation_key,
        }
        warnings: list[str] = [
            "Ensemble disagreement is deferred until multiple compatible probability "
            "vectors are persisted for the same image."
        ]
        if selection_summary["missing_embedding_count"]:
            warnings.append(
                f"{selection_summary['missing_embedding_count']} images have no matching embedding."
            )
        if selection_summary["stale_embedding_count"]:
            warnings.append(
                f"{selection_summary['stale_embedding_count']} stale embeddings were not used."
            )
        queue.summary_json = {
            **dict(queue.summary_json),
            **selection_summary,
            "candidate_count": len(candidates),
            "selected_count": len(selections),
            "reviewed_excluded": reviewed_excluded,
            "below_threshold_excluded": below_threshold_excluded,
            "average_selection_score": (
                round(
                    mean(selection.candidate.item.score for selection, _result in selections),
                    2,
                )
                if selections
                else 0.0
            ),
            "average_diversity_score": (
                round(
                    mean(result.diversity for _selection, result in selections),
                    4,
                )
                if selections
                else 0.0
            ),
            "top_image_ids": [
                selection.candidate.item.image_id for selection, _result in selections[:10]
            ],
            "counts_by_group": dict(
                Counter(
                    selection.candidate.group_key or "ungrouped"
                    for selection, _result in selections
                )
            ),
            "counts_by_fragment": dict(
                Counter(selection.fragment_key or "unassigned" for selection, _ in selections)
            ),
            "selection_reasons": dict(
                Counter(
                    reason
                    for selection, result in selections
                    for reason in _selection_reason_labels(
                        result,
                        has_classes=bool(selection.candidate.item.label_class_ids_json),
                    )
                )
            ),
            "warnings": warnings,
        }
        queue.status = "complete"
        queue.completed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(queue)
        if request.create_cycle:
            self._create_cycle_for_queue(queue, request)
            self.session.refresh(queue)
        return ReviewQueueResponse.model_validate(queue)

    def promote(
        self,
        queue_id: str,
        request: ActiveLearningQueuePromotionRequest,
    ) -> ActiveLearningQueuePromotionResponse:
        queue = self.session.get(ReviewQueue, queue_id)
        if queue is None:
            raise NotFoundError("Active-learning queue not found")
        if queue.formula_id != ACTIVE_LEARNING_FORMULA_ID:
            raise ValidationError("Only active-learning queues can be promoted")
        if queue.promoted_dataset_version_id and queue.promoted_at:
            return ActiveLearningQueuePromotionResponse(
                queue_id=queue.id,
                queue_revision=queue.revision,
                dataset_version_id=queue.promoted_dataset_version_id,
                cycle_id=queue.promoted_cycle_id,
                promoted_at=queue.promoted_at.isoformat(),
                idempotent_replay=True,
            )
        items = list(
            self.session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.review_queue_id == queue.id)
                .order_by(ReviewQueueItem.rank_position)
            )
        )
        unfinished = [
            item.id for item in items if item.review_state not in {"completed", "skipped"}
        ]
        if unfinished:
            raise ConflictError(
                "Complete or explicitly skip every queued review before dataset promotion"
            )
        completed_items = [item for item in items if item.review_state == "completed"]
        if not completed_items:
            raise ConflictError("At least one reviewed item is required for dataset promotion")
        completed_image_ids = [item.image_id for item in completed_items]
        reviewed_image_ids = set(
            self.session.scalars(
                select(ImageAsset.id).where(
                    ImageAsset.id.in_(completed_image_ids),
                    ImageAsset.project_id == queue.project_id,
                    ImageAsset.annotation_status == "reviewed",
                )
            )
        )
        if reviewed_image_ids != set(completed_image_ids):
            raise ConflictError(
                "Every completed queue item must have a reviewed annotation state before promotion"
            )

        cycle: ActiveLearningCycle | None = None
        if request.cycle_id:
            cycle = self.session.get(ActiveLearningCycle, request.cycle_id)
        else:
            cycle = self.session.scalar(
                select(ActiveLearningCycle)
                .where(ActiveLearningCycle.review_queue_id == queue.id)
                .order_by(ActiveLearningCycle.cycle_index.desc())
            )
        if cycle is not None and (
            cycle.project_id != queue.project_id or cycle.review_queue_id != queue.id
        ):
            raise ValidationError("Cycle must belong to this active-learning queue")
        if request.cycle_id and cycle is None:
            raise NotFoundError("Active-learning cycle not found")
        if cycle is not None and cycle.status != "review":
            raise ConflictError("Only a cycle in review can promote its queue")

        version_service = MeasurementAwareDatasetVersionService(self.session, self.settings)
        try:
            version = version_service.create_version(
                queue.project_id,
                DatasetVersionCreateRequest(
                    name=request.name,
                    notes=request.notes
                    or f"Promoted from active-learning queue {queue.id} revision {queue.revision}.",
                    creator=request.creator,
                    parent_version_id=request.parent_version_id,
                    eligible_annotation_statuses=["reviewed"],
                    split_method=request.split_method,
                    split_seed=request.split_seed,
                    reuse_parent_assignments=request.parent_version_id is not None,
                ),
                commit=False,
            )
            promoted_at = datetime.now(UTC)
            annotation_ids = list(
                self.session.scalars(
                    select(Annotation.id).where(Annotation.image_id.in_(completed_image_ids))
                )
            )
            mask_ids = list(
                self.session.scalars(
                    select(MaskAnnotation.id).where(
                        MaskAnnotation.image_id.in_(completed_image_ids)
                    )
                )
            )
            accepted_ids = sorted(set(annotation_ids + mask_ids))
            rejected_ids = sorted(item.id for item in items if item.review_state == "skipped")
            if cycle is not None:
                cycle.reviewed_count = len(items)
                cycle.dataset_version_id = version.id
                cycle.status = "dataset_frozen"
                cycle.accepted_annotation_ids_json = accepted_ids
                cycle.rejected_item_ids_json = rejected_ids
                cycle.selection_result_json = {
                    **dict(cycle.selection_result_json or {}),
                    "reviewed_image_ids": sorted(item.image_id for item in items),
                    "completed_review_image_ids": sorted(completed_image_ids),
                    "skipped_image_ids": sorted(
                        item.image_id for item in items if item.review_state == "skipped"
                    ),
                }
                cycle.history_json = [
                    *list(cycle.history_json or []),
                    {
                        "event_type": "queue_promoted",
                        "timestamp": promoted_at.isoformat(),
                        "queue_id": queue.id,
                        "queue_revision": queue.revision,
                        "dataset_version_id": version.id,
                        "accepted_annotation_count": len(accepted_ids),
                        "rejected_item_count": len(rejected_ids),
                    },
                ]
            queue.promoted_dataset_version_id = version.id
            queue.promoted_cycle_id = cycle.id if cycle else None
            queue.promoted_at = promoted_at
            queue.summary_json = {
                **dict(queue.summary_json),
                "promotion": {
                    "dataset_version_id": version.id,
                    "cycle_id": cycle.id if cycle else None,
                    "queue_revision": queue.revision,
                    "accepted_annotation_ids": accepted_ids,
                    "rejected_item_ids": rejected_ids,
                    "promoted_at": promoted_at.isoformat(),
                },
            }
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return ActiveLearningQueuePromotionResponse(
            queue_id=queue.id,
            queue_revision=queue.revision,
            dataset_version_id=version.id,
            cycle_id=cycle.id if cycle else None,
            promoted_at=promoted_at.isoformat(),
        )
