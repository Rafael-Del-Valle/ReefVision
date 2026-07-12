"""Annotation editor services."""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Annotation, AnnotationEvent, ImageAsset, Project
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotations import (
    AnnotationBatchSaveRequest,
    AnnotationBatchSaveResponse,
    AnnotationCountResponse,
    AnnotationDraft,
    AnnotationResponse,
    AnnotationSessionResponse,
)
from reefvision.schemas.images import ImageResponse
from reefvision.schemas.projects import LabelClassResponse


def annotation_snapshot(annotation: Annotation) -> dict[str, object | None]:
    return {
        "id": annotation.id,
        "image_id": annotation.image_id,
        "label_class_id": annotation.label_class_id,
        "x_min": annotation.x_min,
        "y_min": annotation.y_min,
        "x_max": annotation.x_max,
        "y_max": annotation.y_max,
        "source_type": annotation.source_type,
        "source_model_id": annotation.source_model_id,
        "source_prediction_id": annotation.source_prediction_id,
        "provenance_json": annotation.provenance_json,
        "created_by": annotation.created_by,
        "deleted_at": annotation.deleted_at.isoformat() if annotation.deleted_at else None,
        "revision": annotation.revision,
    }


class AnnotationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.annotations = AnnotationRepository(session)
        self.images = ImageRepository(session)
        self.projects = ProjectRepository(session)

    def _image(self, image_id: str) -> ImageAsset:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _project_with_classes(self, image: ImageAsset) -> Project:
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _neighbor_ids(self, image: ImageAsset) -> tuple[str | None, str | None]:
        return self.images.neighbor_ids_for_image(image)

    def _counts_by_class(
        self, project: Project, annotations: list[Annotation]
    ) -> list[AnnotationCountResponse]:
        counts = Counter(
            annotation.label_class_id for annotation in annotations if annotation.deleted_at is None
        )
        return [
            AnnotationCountResponse(
                label_class_id=label_class.id,
                count=counts.get(label_class.id, 0),
            )
            for label_class in project.label_classes
        ]

    def get_annotation_session(self, image_id: str) -> AnnotationSessionResponse:
        image = self._image(image_id)
        project = self._project_with_classes(image)
        annotations = self.annotations.list_for_image(image_id)
        previous_image_id, next_image_id = self._neighbor_ids(image)
        return AnnotationSessionResponse(
            image=ImageResponse.model_validate(image),
            label_classes=[
                LabelClassResponse.model_validate(label_class)
                for label_class in project.label_classes
            ],
            annotations=[
                AnnotationResponse.model_validate(annotation) for annotation in annotations
            ],
            counts_by_class=self._counts_by_class(project, annotations),
            previous_image_id=previous_image_id,
            next_image_id=next_image_id,
        )

    def _validate_annotation_box(self, annotation: AnnotationDraft, image: ImageAsset) -> None:
        if annotation.x_max <= annotation.x_min or annotation.y_max <= annotation.y_min:
            raise ValidationError("Bounding boxes must have positive width and height")
        if annotation.x_min < 0 or annotation.y_min < 0:
            raise ValidationError("Bounding boxes cannot start outside the image")
        if annotation.x_max > image.width_px or annotation.y_max > image.height_px:
            raise ValidationError("Bounding boxes cannot extend outside the image bounds")

    def _event(
        self,
        *,
        annotation: Annotation,
        image_id: str,
        event_type: str,
        before_json: dict[str, object | None] | None,
        after_json: dict[str, object | None] | None,
    ) -> AnnotationEvent:
        return AnnotationEvent(
            annotation_id=annotation.id,
            image_id=image_id,
            event_type=event_type,
            before_json=before_json,
            after_json=after_json,
            actor="local_user",
        )

    def save_annotations(
        self, image_id: str, payload: AnnotationBatchSaveRequest
    ) -> AnnotationBatchSaveResponse:
        image = self._image(image_id)
        if image.annotation_revision != payload.base_revision:
            raise ConflictError("Annotation revision conflict")

        project = self._project_with_classes(image)
        project_classes = {label_class.id: label_class for label_class in project.label_classes}
        existing_annotations = self.annotations.list_for_image(image_id, include_deleted=True)
        existing_by_id = {annotation.id: annotation for annotation in existing_annotations}
        desired_ids = {annotation.id for annotation in payload.annotations}
        changed = False

        for draft in payload.annotations:
            self._validate_annotation_box(draft, image)
            label_class = project_classes.get(draft.label_class_id)
            if label_class is None:
                raise ValidationError("Annotation class does not belong to this image's project")

            existing = existing_by_id.get(draft.id)
            if existing is None:
                annotation = Annotation(
                    id=draft.id,
                    image_id=image_id,
                    label_class_id=draft.label_class_id,
                    x_min=draft.x_min,
                    y_min=draft.y_min,
                    x_max=draft.x_max,
                    y_max=draft.y_max,
                )
                self.annotations.add(annotation)
                self.annotations.add_event(
                    self._event(
                        annotation=annotation,
                        image_id=image_id,
                        event_type="created",
                        before_json=None,
                        after_json=annotation_snapshot(annotation),
                    )
                )
                changed = True
                continue

            if existing.image_id != image_id:
                raise ValidationError("Annotations may only be saved back to their source image")

            before = annotation_snapshot(existing)
            class_changed = existing.label_class_id != draft.label_class_id
            geometry_changed = (
                existing.x_min != draft.x_min
                or existing.y_min != draft.y_min
                or existing.x_max != draft.x_max
                or existing.y_max != draft.y_max
            )
            restored = existing.deleted_at is not None

            if class_changed or geometry_changed or restored:
                existing.label_class_id = draft.label_class_id
                existing.x_min = draft.x_min
                existing.y_min = draft.y_min
                existing.x_max = draft.x_max
                existing.y_max = draft.y_max
                if restored:
                    existing.deleted_at = None
                existing.revision += 1
                event_type = (
                    "restored" if restored else "class_changed" if class_changed else "updated"
                )
                self.annotations.add_event(
                    self._event(
                        annotation=existing,
                        image_id=image_id,
                        event_type=event_type,
                        before_json=before,
                        after_json=annotation_snapshot(existing),
                    )
                )
                changed = True

        for annotation in existing_annotations:
            if annotation.deleted_at is None and annotation.id not in desired_ids:
                before = annotation_snapshot(annotation)
                annotation.deleted_at = utc_now()
                annotation.revision += 1
                self.annotations.add_event(
                    self._event(
                        annotation=annotation,
                        image_id=image_id,
                        event_type="deleted",
                        before_json=before,
                        after_json=annotation_snapshot(annotation),
                    )
                )
                changed = True

        if image.annotation_status != payload.annotation_status:
            image.annotation_status = payload.annotation_status
            changed = True

        if changed:
            image.annotation_revision += 1
            self.session.commit()

        refreshed_image = self._image(image_id)
        active_annotations = self.annotations.list_for_image(image_id)
        return AnnotationBatchSaveResponse(
            image=ImageResponse.model_validate(refreshed_image),
            annotations=[
                AnnotationResponse.model_validate(annotation) for annotation in active_annotations
            ],
            counts_by_class=self._counts_by_class(project, active_annotations),
        )
