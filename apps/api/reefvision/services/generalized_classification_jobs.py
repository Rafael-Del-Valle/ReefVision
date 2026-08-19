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


def _normalized_scope(value: object) -> str:
    scope = str(value or "").strip().casefold()
    if scope == "annotation_crop":
        return "annotation"
    return scope


def _require_snapshot_preprocessing_match(
    model_metadata: dict[str, object],
    request: ClassificationInferenceRequest,
) -> None:
    if request.target_kind not in {"mask", "fragment"}:
        return
    trained_minimum = int(model_metadata.get("minimum_crop_size_px", 10))
    trained_padding = float(model_metadata.get("padding_fraction", 0.0))
    trained_background = str(model_metadata.get("mask_background", "black"))
    if request.minimum_crop_size_px != trained_minimum:
        raise ValidationError(
            "Snapshot-derived classifiers must use the same minimum crop size used during "
            f"training ({trained_minimum}px)"
        )
    if abs(request.padding_fraction - trained_padding) > 1e-12:
        raise ValidationError(
            "Snapshot-derived classifiers must use the same crop padding used during training "
            f"({trained_padding})"
        )
    if request.mask_background != trained_background:
        raise ValidationError(
            "Snapshot-derived classifiers must use the same mask background used during training "
            f"({trained_background!r})"
        )


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

        model_metadata = dict(model.metadata_json or {})
        class_map = dict(model.class_map_json or {})
        scope_locked = bool(
            model_metadata.get("classification_scope_locked")
            or class_map.get("classification_scope_locked")
        )
        trained_scope = _normalized_scope(
            model_metadata.get("classification_scope")
            or class_map.get("classification_scope")
        )
        if scope_locked and trained_scope and trained_scope != request.target_kind:
            raise ValidationError(
                f"This classifier is locked to {trained_scope!r} targets because that is the "
                f"immutable target kind it was trained on; requested {request.target_kind!r}"
            )
        trained_label_set = str(
            model_metadata.get("classification_label_set_key")
            or class_map.get("classification_label_set_key")
            or ""
        ).strip()
        if scope_locked and trained_label_set and trained_label_set != request.label_set:
            raise ValidationError(
                f"This classifier was trained for classification label set {trained_label_set!r}; "
                f"requested {request.label_set!r}"
            )
        if scope_locked:
            _require_snapshot_preprocessing_match(model_metadata, request)

        requested_images = list(dict.fromkeys(request.image_ids))
        images = (
            list(
                self.session.scalars(
                    select(ImageAsset).where(ImageAsset.id.in_(requested_images))
                )
            )
            if requested_images
            else []
        )
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
                    query.order_by(
                        MaskAnnotation.image_id,
                        MaskAnnotation.created_at,
                        MaskAnnotation.id,
                    )
                )
            )
            if requested_masks and len(masks) != len(requested_masks):
                raise ValidationError(
                    "One or more requested masks do not exist, are unverified, "
                    "or belong to another project"
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
                "trained_classification_scope": trained_scope or None,
                "trained_classification_label_set": trained_label_set or None,
                "classification_scope_locked": scope_locked,
                "preprocessing_locked": scope_locked,
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)
