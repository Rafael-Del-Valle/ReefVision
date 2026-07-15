"""Mask-annotation persistence operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import MaskAnnotation, MaskAnnotationEvent


class MaskAnnotationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, annotation: MaskAnnotation) -> None:
        self.session.add(annotation)

    def add_event(self, event: MaskAnnotationEvent) -> None:
        self.session.add(event)

    def get(self, annotation_id: str) -> MaskAnnotation | None:
        return self.session.get(MaskAnnotation, annotation_id)

    def list_for_image(
        self,
        image_id: str,
        *,
        include_deleted: bool = False,
    ) -> list[MaskAnnotation]:
        statement = select(MaskAnnotation).where(MaskAnnotation.image_id == image_id)
        if not include_deleted:
            statement = statement.where(MaskAnnotation.deleted_at.is_(None))
        statement = statement.order_by(MaskAnnotation.created_at, MaskAnnotation.id)
        return list(self.session.scalars(statement))

    def counts_for_image(self, image_id: str) -> dict[str, int]:
        statement = (
            select(MaskAnnotation.label_class_id, func.count(MaskAnnotation.id))
            .where(
                MaskAnnotation.image_id == image_id,
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.label_class_id.is_not(None),
            )
            .group_by(MaskAnnotation.label_class_id)
        )
        return {
            label_class_id: int(count)
            for label_class_id, count in self.session.execute(statement)
            if label_class_id is not None
        }
