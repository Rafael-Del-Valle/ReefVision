"""Persistence helpers for class-visibility preferences and defaults."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from reefvision.db.models.class_visibility_preference import ClassVisibilityPreference
from reefvision.db.models.project import utc_now
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

    def delete_if_updated_at(
        self, project_id: str, user_identity: str, layer_type: str, expected_updated_at: datetime
    ) -> bool:
        """Delete only the saved personal preference version observed by this editor."""
        result = self.session.connection().execute(
            delete(ClassVisibilityPreference).where(
                ClassVisibilityPreference.project_id == project_id,
                ClassVisibilityPreference.user_identity == user_identity,
                ClassVisibilityPreference.layer_type == layer_type,
                ClassVisibilityPreference.updated_at == expected_updated_at,
            )
        )
        return result.rowcount == 1

    def save_if_revision(
        self,
        project_id: str,
        user_identity: str,
        layer_type: str,
        hidden_class_ids: list[str],
        expected_updated_at: datetime | None,
    ) -> bool:
        """Atomic compare-and-save. None means create only if the scope is absent."""
        if expected_updated_at is None:
            insert_statement = (
                sqlite_insert(ClassVisibilityPreference)
                .values(
                    project_id=project_id,
                    user_identity=user_identity,
                    layer_type=layer_type,
                    hidden_class_ids_json=hidden_class_ids,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ClassVisibilityPreference.project_id,
                        ClassVisibilityPreference.user_identity,
                        ClassVisibilityPreference.layer_type,
                    ]
                )
            )
        else:
            update_statement = (
                update(ClassVisibilityPreference)
                .where(
                    ClassVisibilityPreference.project_id == project_id,
                    ClassVisibilityPreference.user_identity == user_identity,
                    ClassVisibilityPreference.layer_type == layer_type,
                    ClassVisibilityPreference.updated_at == expected_updated_at,
                )
                .values(hidden_class_ids_json=hidden_class_ids, updated_at=utc_now())
            )
        if expected_updated_at is None:
            return self.session.connection().execute(insert_statement).rowcount == 1
        return self.session.connection().execute(update_statement).rowcount == 1

    def upsert(
        self, project_id: str, user_identity: str, layer_type: str, hidden_class_ids: list[str]
    ) -> None:
        """Atomically replace one user's layer, even if two editors save its first row.

        The unique project/user/layer constraint serializes concurrent first writes.
        SQLite remains the local-first storage backend; this is not a blind
        check-then-insert and does not mutate scientific observations.
        """
        statement = sqlite_insert(ClassVisibilityPreference).values(
            project_id=project_id,
            user_identity=user_identity,
            layer_type=layer_type,
            hidden_class_ids_json=hidden_class_ids,
        )
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    ClassVisibilityPreference.project_id,
                    ClassVisibilityPreference.user_identity,
                    ClassVisibilityPreference.layer_type,
                ],
                set_={
                    "hidden_class_ids_json": hidden_class_ids,
                    "updated_at": utc_now(),
                },
            )
        )


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

    def delete_if_updated_at(
        self, project_id: str, layer_type: str, expected_updated_at: datetime
    ) -> bool:
        """Atomically delete only the version observed by this editor."""
        result = self.session.connection().execute(
            delete(ProjectClassVisibilityDefault).where(
                ProjectClassVisibilityDefault.project_id == project_id,
                ProjectClassVisibilityDefault.layer_type == layer_type,
                ProjectClassVisibilityDefault.updated_at == expected_updated_at,
            )
        )
        return result.rowcount == 1

    def save_if_revision(
        self,
        project_id: str,
        layer_type: str,
        hidden_class_ids: list[str],
        updated_by_identity: str,
        expected_updated_at: datetime | None,
    ) -> bool:
        """Create or update only the project-default revision observed by the editor."""
        if expected_updated_at is None:
            insert_statement = (
                sqlite_insert(ProjectClassVisibilityDefault)
                .values(
                    project_id=project_id,
                    layer_type=layer_type,
                    hidden_class_ids_json=hidden_class_ids,
                    updated_by_identity=updated_by_identity,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ProjectClassVisibilityDefault.project_id,
                        ProjectClassVisibilityDefault.layer_type,
                    ]
                )
            )
        else:
            update_statement = (
                update(ProjectClassVisibilityDefault)
                .where(
                    ProjectClassVisibilityDefault.project_id == project_id,
                    ProjectClassVisibilityDefault.layer_type == layer_type,
                    ProjectClassVisibilityDefault.updated_at == expected_updated_at,
                )
                .values(
                    hidden_class_ids_json=hidden_class_ids,
                    updated_by_identity=updated_by_identity,
                    updated_at=utc_now(),
                )
            )
        if expected_updated_at is None:
            return self.session.connection().execute(insert_statement).rowcount == 1
        return self.session.connection().execute(update_statement).rowcount == 1

    def upsert(
        self,
        project_id: str,
        layer_type: str,
        hidden_class_ids: list[str],
        updated_by_identity: str,
    ) -> None:
        """Use the project's unique scope constraint for atomic default saves."""
        statement = sqlite_insert(ProjectClassVisibilityDefault).values(
            project_id=project_id,
            layer_type=layer_type,
            hidden_class_ids_json=hidden_class_ids,
            updated_by_identity=updated_by_identity,
        )
        self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    ProjectClassVisibilityDefault.project_id,
                    ProjectClassVisibilityDefault.layer_type,
                ],
                set_={
                    "hidden_class_ids_json": hidden_class_ids,
                    "updated_by_identity": updated_by_identity,
                    "updated_at": utc_now(),
                },
            )
        )
