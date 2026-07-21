"""Automatic image-embedding job creation and coverage validation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ImageAsset, Job, Project, ProviderModelAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.image_embedding_runtime import ULTRALYTICS_EMBEDDING_PREPROCESSING_VERSION
from reefvision.schemas.image_embeddings import (
    ImageEmbeddingGenerateRequest,
    ImageEmbeddingGenerationResponse,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.storage.datasets import canonical_json_sha256


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
        images = list(self.session.scalars(query.order_by(ImageAsset.created_at, ImageAsset.id)))
        if request.image_ids and len(images) != len(request.image_ids):
            raise ValidationError(
                "All requested embedding images must belong to the selected project"
            )
        if not images:
            raise ValidationError("The project contains no images to embed")
        image_by_id = {image.id: image for image in images}
        for crop in request.crop_boxes:
            image = image_by_id.get(crop.image_id)
            if image is None:
                raise ValidationError("Every embedding crop must target a requested project image")
            if crop.x_max > image.width_px or crop.y_max > image.height_px:
                raise ValidationError("Embedding crops must remain inside the source image")

        model_checksum = request.model_checksum
        model_version = "unknown"
        checkpoint_path: str | None = None
        preprocessing_version = request.preprocessing_version
        if request.provider_id == "ultralytics_backbone":
            asset = self.session.scalar(
                select(ProviderModelAsset).where(ProviderModelAsset.model_id == request.model_id)
            )
            if asset is None:
                raise ValidationError(
                    "Discover and verify the selected local Ultralytics embedding model first"
                )
            if asset.provider_id != "ultralytics" or asset.task not in {"detect", "segment"}:
                raise ValidationError(
                    "The baseline embedding provider requires a registered Ultralytics "
                    "detection or segmentation backbone"
                )
            if not bool(asset.verification_json.get("verified")):
                raise ValidationError("The selected embedding checkpoint is not verified")
            if request.model_checksum and request.model_checksum != asset.checkpoint_sha256:
                raise ValidationError(
                    "Embedding request checksum differs from the registered model"
                )
            model_checksum = asset.checkpoint_sha256
            model_version = asset.provider_version
            checkpoint_path = asset.checkpoint_path
            preprocessing_version = (
                preprocessing_version or ULTRALYTICS_EMBEDDING_PREPROCESSING_VERSION
            )
        else:
            preprocessing_version = preprocessing_version or (
                "reefvision-color-texture-v1"
                if request.provider_id == "color_texture_v1"
                else "transformers-auto-image-processor-v1"
            )

        work_items: list[dict[str, object]] = [
            {"image_id": image.id, "source_kind": "image", "crop": None} for image in images
        ]
        work_items.extend(
            {
                "image_id": crop.image_id,
                "source_kind": "crop",
                "crop": {
                    "x_min": crop.x_min,
                    "y_min": crop.y_min,
                    "x_max": crop.x_max,
                    "y_max": crop.y_max,
                },
            }
            for crop in request.crop_boxes
        )
        generation_key = canonical_json_sha256(
            {
                "project_id": project.id,
                "provider_id": request.provider_id,
                "model_id": request.model_id,
                "model_checksum": model_checksum,
                "model_version": model_version,
                "preprocessing_version": preprocessing_version,
                "device": request.device,
                "work_items": work_items,
                "source_checksums": {image.id: image.sha256 for image in images},
            }
        )
        existing_jobs = list(
            self.session.scalars(
                select(Job)
                .where(
                    Job.project_id == project.id,
                    Job.job_type == "image_embeddings",
                    Job.status.in_(("queued", "running", "succeeded")),
                )
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        )
        existing = next(
            (
                item
                for item in existing_jobs
                if item.request_json.get("generation_key") == generation_key
            ),
            None,
        )
        if existing is not None:
            return ImageEmbeddingGenerationResponse(
                embedding_model_id=request.model_id,
                requested_image_count=len(work_items),
                job=JobResponse.model_validate(existing),
            )
        job = Job(
            project_id=project.id,
            job_type="image_embeddings",
            status="queued",
            progress_total=len(work_items),
            max_retries=1,
            resume_supported=True,
            request_json={
                **request.model_dump(mode="json"),
                "project_id": project.id,
                "resolved_image_ids": [image.id for image in images],
                "resolved_work_items": work_items,
                "resolved_model_checksum": model_checksum,
                "resolved_model_version": model_version,
                "resolved_checkpoint_path": checkpoint_path,
                "resolved_preprocessing_version": preprocessing_version,
                "generation_key": generation_key,
            },
            checkpoint_json={"completed_embedding_keys": []},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ImageEmbeddingGenerationResponse(
            embedding_model_id=request.model_id,
            requested_image_count=len(work_items),
            job=JobResponse.model_validate(job),
        )
