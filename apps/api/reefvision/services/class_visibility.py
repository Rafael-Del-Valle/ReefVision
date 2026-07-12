"""Services for persisted class-visibility preferences and defaults."""

from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.class_visibility_preference import ClassVisibilityPreference
from reefvision.db.models.project_class_visibility_default import (
    ProjectClassVisibilityDefault,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.class_visibility import (
    ClassVisibilityPreferenceRepository,
    ProjectClassVisibilityDefaultRepository,
)
from reefvision.repositories.projects import LabelClassRepository, ProjectRepository
from reefvision.schemas.class_visibility import (
    SUPPORTED_CLASS_VISIBILITY_LAYER_TYPES,
    VISIBILITY_PRECEDENCE,
    ClassVisibilityBundleResponse,
    ClassVisibilityLayerType,
    ClassVisibilityScopeStateResponse,
    ClassVisibilityUpdateRequest,
)
from reefvision.storage.identity import get_local_user_identity


class ClassVisibilityService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.classes = LabelClassRepository(session)
        self.preferences = ClassVisibilityPreferenceRepository(session)
        self.project_defaults = ProjectClassVisibilityDefaultRepository(session)

    def _project(self, project_id: str) -> None:
        if self.projects.get(project_id) is None:
            raise NotFoundError("Project not found")

    def _layer_type(self, layer_type: str) -> ClassVisibilityLayerType:
        if layer_type not in SUPPORTED_CLASS_VISIBILITY_LAYER_TYPES:
            raise ValidationError("Unsupported class-visibility layer type")
        return cast(ClassVisibilityLayerType, layer_type)

    def _project_class_ids(self, project_id: str) -> tuple[str, ...]:
        return tuple(label_class.id for label_class in self.classes.list_for_project(project_id))

    def _sanitize_hidden_class_ids(
        self, hidden_class_ids: list[str], valid_class_ids: tuple[str, ...]
    ) -> list[str]:
        valid = set(valid_class_ids)
        return [class_id for class_id in dict.fromkeys(hidden_class_ids) if class_id in valid]

    def _validated_hidden_class_ids(
        self, project_id: str, hidden_class_ids: list[str]
    ) -> tuple[list[str], tuple[str, ...]]:
        valid_class_ids = self._project_class_ids(project_id)
        valid = set(valid_class_ids)
        invalid = [class_id for class_id in hidden_class_ids if class_id not in valid]
        if invalid:
            raise ValidationError("Visibility settings can only reference classes in this project")
        return self._sanitize_hidden_class_ids(hidden_class_ids, valid_class_ids), valid_class_ids

    def _scope_state(
        self,
        *,
        hidden_class_ids: list[str],
        valid_class_ids: tuple[str, ...],
        saved: bool,
        updated_at: object | None,
        updated_by_identity: str | None,
    ) -> ClassVisibilityScopeStateResponse:
        return ClassVisibilityScopeStateResponse(
            saved=saved,
            hidden_class_ids=self._sanitize_hidden_class_ids(hidden_class_ids, valid_class_ids),
            updated_at=updated_at,
            updated_by_identity=updated_by_identity,
        )

    def _empty_scope_state(self) -> ClassVisibilityScopeStateResponse:
        return ClassVisibilityScopeStateResponse(saved=False, hidden_class_ids=[])

    def get_bundle(self, project_id: str) -> ClassVisibilityBundleResponse:
        self._project(project_id)
        valid_class_ids = self._project_class_ids(project_id)
        user_identity = get_local_user_identity(self.settings)
        preferences_by_layer = {
            item.layer_type: item
            for item in self.preferences.list_for_project_user(project_id, user_identity)
        }
        defaults_by_layer = {
            item.layer_type: item
            for item in self.project_defaults.list_for_project(project_id)
        }

        user_preferences: dict[ClassVisibilityLayerType, ClassVisibilityScopeStateResponse] = {}
        project_defaults: dict[ClassVisibilityLayerType, ClassVisibilityScopeStateResponse] = {}
        for layer_type in SUPPORTED_CLASS_VISIBILITY_LAYER_TYPES:
            preference = preferences_by_layer.get(layer_type)
            if preference is None:
                user_preferences[layer_type] = self._empty_scope_state()
            else:
                user_preferences[layer_type] = self._scope_state(
                    hidden_class_ids=preference.hidden_class_ids_json,
                    valid_class_ids=valid_class_ids,
                    saved=True,
                    updated_at=preference.updated_at,
                    updated_by_identity=preference.user_identity,
                )

            project_default = defaults_by_layer.get(layer_type)
            if project_default is None:
                project_defaults[layer_type] = self._empty_scope_state()
            else:
                project_defaults[layer_type] = self._scope_state(
                    hidden_class_ids=project_default.hidden_class_ids_json,
                    valid_class_ids=valid_class_ids,
                    saved=True,
                    updated_at=project_default.updated_at,
                    updated_by_identity=project_default.updated_by_identity,
                )

        return ClassVisibilityBundleResponse(
            project_id=project_id,
            user_identity=user_identity,
            supported_layer_types=list(SUPPORTED_CLASS_VISIBILITY_LAYER_TYPES),
            precedence=list(VISIBILITY_PRECEDENCE),
            user_preferences=user_preferences,
            project_defaults=project_defaults,
        )

    def save_user_preference(
        self,
        project_id: str,
        layer_type: str,
        payload: ClassVisibilityUpdateRequest,
    ) -> ClassVisibilityScopeStateResponse:
        self._project(project_id)
        resolved_layer_type = self._layer_type(layer_type)
        hidden_class_ids, valid_class_ids = self._validated_hidden_class_ids(
            project_id, payload.hidden_class_ids
        )
        user_identity = get_local_user_identity(self.settings)
        preference = self.preferences.get(project_id, user_identity, resolved_layer_type)
        if preference is None:
            preference = ClassVisibilityPreference(
                project_id=project_id,
                user_identity=user_identity,
                layer_type=resolved_layer_type,
                hidden_class_ids_json=hidden_class_ids,
            )
            self.preferences.add(preference)
        else:
            preference.hidden_class_ids_json = hidden_class_ids
        self.session.commit()
        self.session.refresh(preference)
        return self._scope_state(
            hidden_class_ids=preference.hidden_class_ids_json,
            valid_class_ids=valid_class_ids,
            saved=True,
            updated_at=preference.updated_at,
            updated_by_identity=preference.user_identity,
        )

    def reset_user_preference(self, project_id: str, layer_type: str) -> None:
        self._project(project_id)
        resolved_layer_type = self._layer_type(layer_type)
        user_identity = get_local_user_identity(self.settings)
        preference = self.preferences.get(project_id, user_identity, resolved_layer_type)
        if preference is not None:
            self.session.delete(preference)
            self.session.commit()

    def save_project_default(
        self,
        project_id: str,
        layer_type: str,
        payload: ClassVisibilityUpdateRequest,
    ) -> ClassVisibilityScopeStateResponse:
        self._project(project_id)
        resolved_layer_type = self._layer_type(layer_type)
        hidden_class_ids, valid_class_ids = self._validated_hidden_class_ids(
            project_id, payload.hidden_class_ids
        )
        user_identity = get_local_user_identity(self.settings)
        project_default = self.project_defaults.get(project_id, resolved_layer_type)
        if project_default is None:
            project_default = ProjectClassVisibilityDefault(
                project_id=project_id,
                layer_type=resolved_layer_type,
                hidden_class_ids_json=hidden_class_ids,
                updated_by_identity=user_identity,
            )
            self.project_defaults.add(project_default)
        else:
            project_default.hidden_class_ids_json = hidden_class_ids
            project_default.updated_by_identity = user_identity
        self.session.commit()
        self.session.refresh(project_default)
        return self._scope_state(
            hidden_class_ids=project_default.hidden_class_ids_json,
            valid_class_ids=valid_class_ids,
            saved=True,
            updated_at=project_default.updated_at,
            updated_by_identity=project_default.updated_by_identity,
        )

    def reset_project_default(self, project_id: str, layer_type: str) -> None:
        self._project(project_id)
        resolved_layer_type = self._layer_type(layer_type)
        project_default = self.project_defaults.get(project_id, resolved_layer_type)
        if project_default is not None:
            self.session.delete(project_default)
            self.session.commit()
