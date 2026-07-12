"""Annotation persistence operations."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import Annotation, AnnotationEvent


class AnnotationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, annotation: Annotation) -> None:
        self.session.add(annotation)

    def add_event(self, event: AnnotationEvent) -> None:
        self.session.add(event)

    def list_for_image(self, image_id: str, *, include_deleted: bool = False) -> list[Annotation]:
        statement = select(Annotation).where(Annotation.image_id == image_id)
        if not include_deleted:
            statement = statement.where(Annotation.deleted_at.is_(None))
        statement = statement.order_by(Annotation.created_at, Annotation.id)
        return list(self.session.scalars(statement))

    def counts_for_image(self, image_id: str) -> dict[str, int]:
        statement = (
            select(Annotation.label_class_id, func.count(Annotation.id))
            .where(Annotation.image_id == image_id, Annotation.deleted_at.is_(None))
            .group_by(Annotation.label_class_id)
        )
        return {
            label_class_id: int(count) for label_class_id, count in self.session.execute(statement)
        }

    def count_for_model(self, model_id: str) -> int:
        statement = select(func.count(Annotation.id)).where(
            Annotation.source_model_id == model_id,
            Annotation.deleted_at.is_(None),
        )
        return int(self.session.scalar(statement) or 0)
