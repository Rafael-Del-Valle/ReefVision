"""Automatic image-embedding job creation and coverage validation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ImageAsset, Job, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.image_embeddings import (
    ImageEmbeddingGenerateRequest,
    ImageEmbeddingGenerationResponse,
)
from reefvision.schemas.jobs import JobResponse


class ImageEmbeddingGenerationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def queue(
        self,
        project_id: str,
        request: ImageEmbeddingGenerateRequest,
    ) -> ImageEmbeddingGenerationResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        query = select(ImageAsset).where(ImageAsset.project_id == project.id)
        if request.image_ids:
            query = query.where(ImageAsset.id.in_(request.image_ids))
        images = list(
            self.session.scalars(query.order_by(ImageAsset.created_at, ImageAsset.id))
        )
        if request.image_ids and len(images) != len(request.image_ids):
            raise ValidationError(
                "All requested embedding images must belong to the selected project"
            )
        if not images:
            raise ValidationError("The project contains no images to embed")
        job = Job(
            project_id=project.id,
            job_type="image_embeddings",
            status="queued",
            progress_total=len(images),
            request_json={
                **request.model_dump(mode="json"),
                "project_id": project.id,
                "resolved_image_ids": [image.id for image in images],
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ImageEmbeddingGenerationResponse(
            embedding_model_id=request.model_id,
            requested_image_count=len(images),
            job=JobResponse.model_validate(job),
        )
