"""Persisted image embedding, generation, and diversity-selection endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.image_embeddings import (
    EmbeddingDiversitySelectionRequest,
    EmbeddingDiversitySelectionResponse,
    ImageEmbeddingGenerateRequest,
    ImageEmbeddingGenerationResponse,
    ImageEmbeddingResponse,
    ImageEmbeddingWriteRequest,
)
from reefvision.services.embedding_generation import ImageEmbeddingGenerationService
from reefvision.services.image_embeddings import ImageEmbeddingService

router = APIRouter(tags=["image-embeddings"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.put(
    "/images/{image_id}/embedding",
    response_model=ImageEmbeddingResponse,
)
def upsert_image_embedding(
    image_id: str,
    payload: ImageEmbeddingWriteRequest,
    session: DbSession,
) -> ImageEmbeddingResponse:
    return ImageEmbeddingService(session).upsert(image_id, payload)


@router.post(
    "/projects/{project_id}/embedding-jobs",
    response_model=ImageEmbeddingGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_project_embeddings(
    project_id: str,
    payload: ImageEmbeddingGenerateRequest,
    session: DbSession,
) -> ImageEmbeddingGenerationResponse:
    return ImageEmbeddingGenerationService(session).queue(project_id, payload)


@router.get(
    "/projects/{project_id}/embeddings",
    response_model=list[ImageEmbeddingResponse],
)
def list_project_embeddings(
    project_id: str,
    session: DbSession,
    embedding_model_id: Annotated[str | None, Query(max_length=300)] = None,
) -> list[ImageEmbeddingResponse]:
    return ImageEmbeddingService(session).list_project_embeddings(
        project_id,
        embedding_model_id=embedding_model_id,
    )


@router.delete(
    "/image-embeddings/{embedding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_image_embedding(
    embedding_id: str,
    session: DbSession,
) -> None:
    ImageEmbeddingService(session).delete(embedding_id)


@router.post(
    "/projects/{project_id}/embedding-diversity-selection",
    response_model=EmbeddingDiversitySelectionResponse,
)
def select_embedding_diversity_batch(
    project_id: str,
    payload: EmbeddingDiversitySelectionRequest,
    session: DbSession,
) -> EmbeddingDiversitySelectionResponse:
    return ImageEmbeddingService(session).select_diverse_candidates(
        project_id,
        payload,
    )
