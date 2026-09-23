"""Project and label-class request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class LabelClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    class_index: int
    display_order: int
    name: str
    scientific_name: str | None
    state_name: str | None
    description: str | None
    display_color: str
    is_active: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    description: str | None = Field(default=None, max_length=5000)
    georeference_height_offset_m: float = Field(default=0.0, ge=-10000.0, le=10000.0)
    template: Literal["blank", "octocoral"] = "blank"

    @field_validator("name", "slug", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=220)
    description: str | None = Field(default=None, max_length=5000)
    georeference_height_offset_m: float = Field(default=0.0, ge=-10000.0, le=10000.0)

    @field_validator("name", "slug", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: str | None
    storage_root: str
    default_annotation_type: str
    georeference_height_offset_m: float
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    label_classes: list[LabelClassResponse] = []


class ProjectSummaryResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    storage_root: str
    default_annotation_type: str
    georeference_height_offset_m: float
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    label_class_count: int
    active_label_class_count: int


class LabelClassCreate(BaseModel):
    class_index: int = Field(ge=0)
    display_order: int | None = Field(default=None, ge=0)
    name: str = Field(min_length=1, max_length=200)
    scientific_name: str | None = Field(default=None, max_length=200)
    state_name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    display_color: str = Field(pattern=HEX_COLOR_PATTERN)

    @field_validator("name", "scientific_name", "state_name", "description")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class LabelClassUpdate(BaseModel):
    display_order: int | None = Field(default=None, ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    scientific_name: str | None = Field(default=None, max_length=200)
    state_name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    display_color: str | None = Field(default=None, pattern=HEX_COLOR_PATTERN)

    @field_validator("name", "scientific_name", "state_name", "description")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class LabelClassUsageCountResponse(BaseModel):
    key: str
    label: str
    count: int
    mutable: bool
    immutable: bool


class LabelClassUsageResponse(BaseModel):
    class_id: str
    project_id: str
    class_name: str
    is_active: bool
    archived_at: datetime | None
    total_references: int
    mutable_reference_count: int
    immutable_reference_count: int
    can_delete: bool
    delete_blockers: list[str]
    compatibility_warnings: list[str]
    counts: list[LabelClassUsageCountResponse]


class LabelClassMergeRequest(BaseModel):
    target_class_id: str = Field(min_length=1, max_length=36)


class LabelClassMergeCountResponse(BaseModel):
    key: str
    label: str
    count: int


class LabelClassMergeResponse(BaseModel):
    source_class: LabelClassResponse
    target_class: LabelClassResponse
    affected_counts: list[LabelClassMergeCountResponse]
    immutable_reference_counts: list[LabelClassMergeCountResponse]
    warnings: list[str]
