"""Model-registration persistence operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ModelRegistration


class ModelRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, model: ModelRegistration) -> None:
        self.session.add(model)

    def get(self, model_id: str) -> ModelRegistration | None:
        return self.session.get(ModelRegistration, model_id)

    def list_for_project(
        self, project_id: str, *, purpose: str | None = None
    ) -> list[ModelRegistration]:
        statement = select(ModelRegistration).where(ModelRegistration.project_id == project_id)
        if purpose:
            statement = statement.where(ModelRegistration.purpose == purpose)
        statement = statement.order_by(ModelRegistration.created_at.desc(), ModelRegistration.id)
        return list(self.session.scalars(statement))

    def find_by_checksum(self, project_id: str, sha256: str) -> ModelRegistration | None:
        statement = select(ModelRegistration).where(
            ModelRegistration.project_id == project_id,
            ModelRegistration.sha256 == sha256,
        )
        return self.session.scalar(statement)

    def find_by_display_name(self, project_id: str, display_name: str) -> ModelRegistration | None:
        statement = select(ModelRegistration).where(
            ModelRegistration.project_id == project_id,
            ModelRegistration.display_name == display_name,
        )
        return self.session.scalar(statement)
