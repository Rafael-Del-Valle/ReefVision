"""Persistence helpers for class-operation records."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from reefvision.db.models.class_operation import ClassOperation


class ClassOperationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, operation_id: str) -> ClassOperation | None:
        return self.session.get(ClassOperation, operation_id)

    def add(self, operation: ClassOperation) -> None:
        self.session.add(operation)

    def latest_for_source(
        self, project_id: str, source_class_id: str, operation_type: str
    ) -> ClassOperation | None:
        statement = (
            select(ClassOperation)
            .where(
                ClassOperation.project_id == project_id,
                ClassOperation.source_class_id == source_class_id,
                ClassOperation.operation_type == operation_type,
            )
            .order_by(desc(ClassOperation.created_at))
        )
        return self.session.scalar(statement)
