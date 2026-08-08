"""Revisioned image-level classification label operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ImageAsset, ImageLabel, LabelClass
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification import ImageLabelResponse, ImageLabelSetRequest


class ClassificationLabelService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def list_labels(self, image_id: str, label_set: str = "default") -> list[ImageLabelResponse]:
        self._image(image_id)
        statement = (
            select(ImageLabel)
            .where(
                ImageLabel.image_id == image_id,
                ImageLabel.label_set == label_set,
                ImageLabel.deleted_at.is_(None),
            )
            .order_by(ImageLabel.created_at, ImageLabel.id)
        )
        return [ImageLabelResponse.model_validate(item) for item in self.session.scalars(statement)]

    def replace_labels(
        self,
        image_id: str,
        payload: ImageLabelSetRequest,
    ) -> list[ImageLabelResponse]:
        image = self._image(image_id)
        desired_ids = set(payload.label_class_ids)
        if desired_ids:
            valid_ids = set(
                self.session.scalars(
                    select(LabelClass.id).where(
                        LabelClass.project_id == image.project_id,
                        LabelClass.id.in_(desired_ids),
                    )
                )
            )
            if valid_ids != desired_ids:
                raise ValidationError("Classification labels must belong to the image project")

        existing = list(
            self.session.scalars(
                select(ImageLabel).where(
                    ImageLabel.image_id == image_id,
                    ImageLabel.label_set == payload.label_set,
                )
            )
        )
        existing_by_class = {item.label_class_id: item for item in existing}
        changed = False

        for label in existing:
            desired = label.label_class_id in desired_ids
            if desired and label.deleted_at is not None:
                label.deleted_at = None
                label.status = "verified"
                label.source_type = "human"
                label.source_model_id = None
                label.source_prediction_id = None
                label.confidence = None
                label.revision += 1
                changed = True
            elif not desired and label.deleted_at is None:
                label.deleted_at = utc_now()
                label.revision += 1
                changed = True

        for class_id in sorted(desired_ids - set(existing_by_class)):
            self.session.add(
                ImageLabel(
                    image_id=image_id,
                    label_class_id=class_id,
                    label_set=payload.label_set,
                    source_type="human",
                    status="verified",
                    created_by="local_user",
                )
            )
            changed = True

        if changed:
            image.annotation_revision += 1
            self.session.commit()
        return self.list_labels(image_id, payload.label_set)
