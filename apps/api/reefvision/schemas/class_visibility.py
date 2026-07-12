"""Class-visibility request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ClassVisibilityLayerType = Literal[
    "annotations",
    "predictions",
    "qc_overlays",
    "video_tracks",
    "segmentation_overlays",
]

SUPPORTED_CLASS_VISIBILITY_LAYER_TYPES: tuple[ClassVisibilityLayerType, ...] = (
    "annotations",
    "predictions",
    "qc_overlays",
    "video_tracks",
    "segmentation_overlays",
)

VISIBILITY_PRECEDENCE: tuple[str, ...] = (
    "temporary_qc_reveal",
    "session_override",
    "user_preference",
    "project_default",
    "visible_by_default",
)


class ClassVisibilityScopeStateResponse(BaseModel):
    saved: bool
    hidden_class_ids: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    updated_by_identity: str | None = None


class ClassVisibilityBundleResponse(BaseModel):
    project_id: str
    user_identity: str
    supported_layer_types: list[ClassVisibilityLayerType]
    precedence: list[str]
    user_preferences: dict[ClassVisibilityLayerType, ClassVisibilityScopeStateResponse]
    project_defaults: dict[ClassVisibilityLayerType, ClassVisibilityScopeStateResponse]


class ClassVisibilityUpdateRequest(BaseModel):
    hidden_class_ids: list[str] = Field(default_factory=list)

    @field_validator("hidden_class_ids")
    @classmethod
    def unique_hidden_class_ids(cls, value: list[str]) -> list[str]:
        deduplicated = list(dict.fromkeys(value))
        if any(not item for item in deduplicated):
            raise ValueError("Hidden class ids must be non-empty strings")
        return deduplicated
