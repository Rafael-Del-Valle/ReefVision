"""Persistence helpers for class-visibility preferences and defaults."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models.class_visibility_preference import ClassVisibilityPreference
from reefvision.db.models.project_class_visibility_default import ProjectClassVisibilityDefault


class ClassVisibilityPreferenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_project_user(
        self, project_id: str, user_identity: str
    ) -> list[ClassVisibilityPreference]:
        statement = (
            select(ClassVisibilityPreference)
            .where(
                ClassVisibilityPreference.project_id == project_id,
                ClassVisibilityPreference.user_identity == user_identity,
            )
            .order_by(ClassVisibilityPreference.layer_type)
        )
        return list(self.session.scalars(statement))

    def get(
        self, project_id: str, user_identity: str, layer_type: str
    ) -> ClassVisibilityPreference | None:
        statement = select(ClassVisibilityPreference).where(
            ClassVisibilityPreference.project_id == project_id,
            ClassVisibilityPreference.user_identity == user_identity,
            ClassVisibilityPreference.layer_type == layer_type,
        )
        return self.session.scalar(statement)

    def add(self, preference: ClassVisibilityPreference) -> None:
        self.session.add(preference)


class ProjectClassVisibilityDefaultRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_project(self, project_id: str) -> list[ProjectClassVisibilityDefault]:
        statement = (
            select(ProjectClassVisibilityDefault)
            .where(ProjectClassVisibilityDefault.project_id == project_id)
            .order_by(ProjectClassVisibilityDefault.layer_type)
        )
        return list(self.session.scalars(statement))

    def get(self, project_id: str, layer_type: str) -> ProjectClassVisibilityDefault | None:
        statement = select(ProjectClassVisibilityDefault).where(
            ProjectClassVisibilityDefault.project_id == project_id,
            ProjectClassVisibilityDefault.layer_type == layer_type,
        )
        return self.session.scalar(statement)

    def add(self, preference: ProjectClassVisibilityDefault) -> None:
        self.session.add(preference)
