"""Persist visual embeddings and select diverse active-learning candidates."""

from __future__ import annotations

from collections import Counter
from math import sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ImageAsset, ImageEmbedding, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.image_embeddings import (
    EmbeddingDiversitySelectionItem,
    EmbeddingDiversitySelectionRequest,
    EmbeddingDiversitySelectionResponse,
    ImageEmbeddingResponse,
    ImageEmbeddingWriteRequest,
)
from reefvision.storage.datasets import canonical_json_sha256


def _normalized_vector(vector: list[float]) -> tuple[float, ...]:
    magnitude = sqrt(sum(value * value for value in vector))
    if magnitude <= 0:
        raise ValidationError("Embedding vectors cannot be all zero")
    return tuple(value / magnitude for value in vector)


def _cosine_novelty(
    candidate: tuple[float, ...],
    selected: list[tuple[str, tuple[float, ...]]],
) -> tuple[float, str | None]:
    if not selected:
        return 1.0, None
    nearest_image_id: str | None = None
    nearest_distance = 1.0
    for image_id, vector in selected:
        similarity = sum(
            first * second for first, second in zip(candidate, vector, strict=True)
        )
        distance = max(0.0, min(1.0, (1.0 - similarity) / 2.0))
        if distance < nearest_distance or (
            distance == nearest_distance
            and (nearest_image_id is None or image_id < nearest_image_id)
        ):
            nearest_distance = distance
            nearest_image_id = image_id
    return nearest_distance, nearest_image_id


class ImageEmbeddingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def upsert(
        self,
        image_id: str,
        request: ImageEmbeddingWriteRequest,
    ) -> ImageEmbeddingResponse:
        image = self._image(image_id)
        vector = [float(value) for value in request.vector]
        _normalized_vector(vector)
        checksum = canonical_json_sha256(vector)
        embedding = self.session.scalar(
            select(ImageEmbedding).where(
                ImageEmbedding.image_id == image.id,
                ImageEmbedding.embedding_model_id == request.embedding_model_id,
            )
        )
        if embedding is None:
            embedding = ImageEmbedding(
                project_id=image.project_id,
                image_id=image.id,
                embedding_model_id=request.embedding_model_id,
                embedding_model_checksum=request.embedding_model_checksum,
                dimension=len(vector),
                vector_json=vector,
                vector_sha256=checksum,
                source_json=request.source,
            )
            self.session.add(embedding)
        else:
            embedding.embedding_model_checksum = request.embedding_model_checksum
            embedding.dimension = len(vector)
            embedding.vector_json = vector
            embedding.vector_sha256 = checksum
            embedding.source_json = request.source
        self.session.commit()
        self.session.refresh(embedding)
        return ImageEmbeddingResponse.model_validate(embedding)

    def list_project_embeddings(
        self,
        project_id: str,
        *,
        embedding_model_id: str | None,
    ) -> list[ImageEmbeddingResponse]:
        self._project(project_id)
        query = select(ImageEmbedding).where(ImageEmbedding.project_id == project_id)
        if embedding_model_id:
            query = query.where(
                ImageEmbedding.embedding_model_id == embedding_model_id
            )
        rows = list(
            self.session.scalars(
                query.order_by(
                    ImageEmbedding.embedding_model_id,
                    ImageEmbedding.image_id,
                )
            )
        )
        return [ImageEmbeddingResponse.model_validate(item) for item in rows]

    def delete(self, embedding_id: str) -> None:
        embedding = self.session.get(ImageEmbedding, embedding_id)
        if embedding is None:
            raise NotFoundError("Image embedding not found")
        self.session.delete(embedding)
        self.session.commit()

    def select_diverse_candidates(
        self,
        project_id: str,
        request: EmbeddingDiversitySelectionRequest,
    ) -> EmbeddingDiversitySelectionResponse:
        self._project(project_id)
        image_query = select(ImageAsset).where(ImageAsset.project_id == project_id)
        if request.candidate_image_ids:
            image_query = image_query.where(
                ImageAsset.id.in_(request.candidate_image_ids)
            )
        images = list(
            self.session.scalars(
                image_query.order_by(ImageAsset.created_at, ImageAsset.id)
            )
        )
        if request.candidate_image_ids and len(images) != len(
            request.candidate_image_ids
        ):
            raise ValidationError(
                "All candidate images must exist in the selected project"
            )
        image_by_id = {image.id: image for image in images}
        embedding_query = select(ImageEmbedding).where(
            ImageEmbedding.project_id == project_id,
            ImageEmbedding.embedding_model_id == request.embedding_model_id,
            ImageEmbedding.image_id.in_(list(image_by_id)),
        )
        if request.embedding_model_checksum:
            embedding_query = embedding_query.where(
                ImageEmbedding.embedding_model_checksum
                == request.embedding_model_checksum
            )
        embeddings = list(self.session.scalars(embedding_query))
        embedding_by_image = {item.image_id: item for item in embeddings}
        missing_embedding_count = len(images) - len(embedding_by_image)
        if not embeddings:
            return EmbeddingDiversitySelectionResponse(
                project_id=project_id,
                embedding_model_id=request.embedding_model_id,
                embedding_model_checksum=request.embedding_model_checksum,
                candidate_count=len(images),
                selected_count=0,
                skipped_missing_embedding_count=missing_embedding_count,
                vector_dimension=None,
                diversity_weight=request.diversity_weight,
                maximum_items_per_group=request.maximum_items_per_group,
                selections=[],
                warnings=["No matching image embeddings are available."],
            )
        dimensions = {item.dimension for item in embeddings}
        if len(dimensions) != 1:
            raise ValidationError(
                "Matching embeddings use inconsistent vector dimensions"
            )
        dimension = next(iter(dimensions))
        normalized_vectors = {
            item.image_id: _normalized_vector(
                [float(value) for value in item.vector_json]
            )
            for item in embeddings
        }
        raw_scores = {
            image_id: float(request.base_scores.get(image_id, 0.0))
            for image_id in normalized_vectors
        }
        minimum_score = min(raw_scores.values())
        maximum_score = max(raw_scores.values())
        if maximum_score > minimum_score:
            normalized_scores = {
                image_id: (score - minimum_score) / (maximum_score - minimum_score)
                for image_id, score in raw_scores.items()
            }
        elif maximum_score > 0:
            normalized_scores = dict.fromkeys(raw_scores, 1.0)
        else:
            normalized_scores = dict.fromkeys(raw_scores, 0.0)

        selected_vectors: list[tuple[str, tuple[float, ...]]] = []
        selected_ids: set[str] = set()
        group_counts: Counter[str] = Counter()
        selections: list[EmbeddingDiversitySelectionItem] = []
        maximum_items = min(request.maximum_items, len(normalized_vectors))
        while len(selections) < maximum_items:
            options: list[
                tuple[
                    float,
                    float,
                    float,
                    str,
                    str | None,
                    str | None,
                ]
            ] = []
            for image_id, vector in normalized_vectors.items():
                if image_id in selected_ids:
                    continue
                group_key = image_by_id[image_id].group_key
                group_identifier = group_key or "__ungrouped__"
                if (
                    request.maximum_items_per_group is not None
                    and group_counts[group_identifier]
                    >= request.maximum_items_per_group
                ):
                    continue
                novelty, nearest_image_id = _cosine_novelty(
                    vector,
                    selected_vectors,
                )
                base_score = normalized_scores[image_id]
                selection_score = (
                    request.diversity_weight * novelty
                    + (1.0 - request.diversity_weight) * base_score
                )
                options.append(
                    (
                        selection_score,
                        novelty,
                        base_score,
                        image_id,
                        group_key,
                        nearest_image_id,
                    )
                )
            if not options:
                break
            (
                selection_score,
                novelty,
                normalized_base_score,
                image_id,
                group_key,
                nearest_image_id,
            ) = max(
                options,
                key=lambda item: (
                    item[0],
                    item[1],
                    item[2],
                    tuple(-ord(character) for character in item[3]),
                ),
            )
            selected_ids.add(image_id)
            selected_vectors.append((image_id, normalized_vectors[image_id]))
            group_counts[group_key or "__ungrouped__"] += 1
            selections.append(
                EmbeddingDiversitySelectionItem(
                    image_id=image_id,
                    group_key=group_key,
                    rank=len(selections) + 1,
                    base_score=raw_scores[image_id],
                    normalized_base_score=normalized_base_score,
                    novelty_score=novelty,
                    selection_score=selection_score,
                    nearest_selected_image_id=nearest_image_id,
                    vector_sha256=embedding_by_image[image_id].vector_sha256,
                )
            )

        warnings: list[str] = []
        if missing_embedding_count:
            warnings.append(
                f"{missing_embedding_count} candidate images were skipped because a matching "
                "embedding was not available."
            )
        if len(selections) < maximum_items and request.maximum_items_per_group:
            warnings.append(
                "The per-group selection limit prevented the requested batch size."
            )
        return EmbeddingDiversitySelectionResponse(
            project_id=project_id,
            embedding_model_id=request.embedding_model_id,
            embedding_model_checksum=request.embedding_model_checksum,
            candidate_count=len(images),
            selected_count=len(selections),
            skipped_missing_embedding_count=missing_embedding_count,
            vector_dimension=dimension,
            diversity_weight=request.diversity_weight,
            maximum_items_per_group=request.maximum_items_per_group,
            selections=selections,
            warnings=warnings,
        )
