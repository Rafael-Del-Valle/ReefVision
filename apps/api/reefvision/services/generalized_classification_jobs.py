"""Queue classification inference for images, annotations, masks, or fragments."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, Job, MaskAnnotation, ModelRegistration, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.classification import CLASSIFICATION_TASK, CLASSIFIER_PURPOSE
from reefvision.schemas.classification import ClassificationInferenceRequest
from reefvision.schemas.jobs import JobResponse
from reefvision.storage.projects import resolve_managed_project_path


class GeneralizedClassificationJobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def create(
        self,
        project_id: str,
        request: ClassificationInferenceRequest,
    ) -> JobResponse:
        project = self._project(project_id)
        model = self.session.get(ModelRegistration, request.model_id)
        if (
            model is None
            or model.project_id != project.id
            or model.purpose != CLASSIFIER_PURPOSE
            or model.task != CLASSIFICATION_TASK
        ):
            raise ValidationError("Choose a registered classifier from this project")
        checkpoint = resolve_managed_project_path(self.settings, model.managed_path)
        if not checkpoint.is_file():
            raise ValidationError("The registered classifier checkpoint is missing")

        requested_images = list(dict.fromkeys(request.image_ids))
        images = list(
            self.session.scalars(
                select(ImageAsset).where(ImageAsset.id.in_(requested_images))
            )
        ) if requested_images else []
        if len(images) != len(requested_images):
            raise ValidationError("One or more requested images do not exist")
        if any(image.project_id != project.id for image in images):
            raise ValidationError("All inference images must belong to the selected project")

        requested_masks = list(dict.fromkeys(request.mask_annotation_ids))
        masks: list[MaskAnnotation] = []
        if request.target_kind in {"mask", "fragment"}:
            query = (
                select(MaskAnnotation)
                .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
                .where(
                    ImageAsset.project_id == project.id,
                    MaskAnnotation.deleted_at.is_(None),
                    MaskAnnotation.status == "verified",
                )
            )
            if requested_masks:
                query = query.where(MaskAnnotation.id.in_(requested_masks))
            elif requested_images:
                query = query.where(MaskAnnotation.image_id.in_(requested_images))
            masks = list(
                self.session.scalars(
                    query.order_by(MaskAnnotation.image_id, MaskAnnotation.created_at, MaskAnnotation.id)
                )
            )
            if requested_masks and len(masks) != len(requested_masks):
                raise ValidationError(
                    "One or more requested masks do not exist, are unverified, or belong to another project"
                )
            if requested_images and any(mask.image_id not in requested_images for mask in masks):
                raise ValidationError("Requested masks must belong to the selected images")
            if not masks:
                raise ValidationError("No verified masks are available for classification")
            if not requested_images:
                requested_images = list(dict.fromkeys(mask.image_id for mask in masks))
                images = list(
                    self.session.scalars(
                        select(ImageAsset).where(ImageAsset.id.in_(requested_images))
                    )
                )
            requested_masks = [mask.id for mask in masks]

        if not requested_images:
            raise ValidationError("Classification inference requires at least one source image")

        job = Job(
            project_id=project.id,
            job_type="classification_inference",
            status="queued",
            progress_total=len(requested_images),
            request_json={
                **request.model_dump(mode="json"),
                "image_ids": requested_images,
                "mask_annotation_ids": requested_masks,
                "model_task": CLASSIFICATION_TASK,
                "model_checksum": model.sha256,
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)
