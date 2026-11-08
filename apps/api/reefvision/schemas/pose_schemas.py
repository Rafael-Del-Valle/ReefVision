"""Project anatomical skeleton template API contracts."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

LANDMARK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,99}$")


class AnatomyLandmarkDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    group: str | None = Field(default=None, max_length=100)
    repeat_group: str | None = Field(default=None, max_length=100)
    repeat_index: int | None = Field(default=None, ge=0, le=999)
    symmetric_with: str | None = Field(default=None, max_length=100)
    required: bool = True

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        normalized = value.strip()
        if not LANDMARK_ID_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Landmark IDs must start with a lowercase letter and use only "
                "lowercase letters, numbers, underscores, or hyphens"
            )
        return normalized

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("description", "group", "repeat_group", "symmetric_with")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def repeat_fields_are_paired(self) -> AnatomyLandmarkDefinition:
        if (self.repeat_group is None) != (self.repeat_index is None):
            raise ValueError("Repeat group and repeat index must be provided together")
        if self.symmetric_with == self.id:
            raise ValueError("A landmark cannot be symmetric with itself")
        return self


class AnatomySkeletonEdge(BaseModel):
    from_id: str = Field(min_length=1, max_length=100)
    to_id: str = Field(min_length=1, max_length=100)

    @field_validator("from_id", "to_id")
    @classmethod
    def strip_id(cls, value: str) -> str:
        return value.strip()


class AnatomyRevisionRequest(BaseModel):
    landmarks: list[AnatomyLandmarkDefinition] = Field(min_length=1, max_length=1000)
    edges: list[AnatomySkeletonEdge] = Field(default_factory=list, max_length=4000)

    @model_validator(mode="after")
    def validate_graph(self) -> AnatomyRevisionRequest:
        ids = [item.id for item in self.landmarks]
        if len(ids) != len(set(ids)):
            raise ValueError("Landmark IDs must be unique")
        known = set(ids)
        repeats: set[tuple[str, int]] = set()
        for landmark in self.landmarks:
            if landmark.repeat_group is not None and landmark.repeat_index is not None:
                slot = (landmark.repeat_group.casefold(), landmark.repeat_index)
                if slot in repeats:
                    raise ValueError("Repeat group indices must be unique")
                repeats.add(slot)
            partner = landmark.symmetric_with
            if partner is not None:
                if partner not in known:
                    raise ValueError("Symmetry relationships must reference a landmark ID")
                other = next(item for item in self.landmarks if item.id == partner)
                if other.symmetric_with != landmark.id:
                    raise ValueError("Symmetry relationships must be reciprocal")

        seen_edges: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.from_id not in known or edge.to_id not in known:
                raise ValueError("Skeleton edges must reference existing landmark IDs")
            if edge.from_id == edge.to_id:
                raise ValueError("Skeleton edges cannot connect a landmark to itself")
            identity = (
                min(edge.from_id, edge.to_id),
                max(edge.from_id, edge.to_id),
            )
            if identity in seen_edges:
                raise ValueError("Skeleton edges must be unique")
            seen_edges.add(identity)
        return self


class AnatomySchemaCreateRequest(AnatomyRevisionRequest):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def strip_schema_name(cls, value: str) -> str:
        return value.strip()


class AnatomyLandmarkGroupResponse(BaseModel):
    name: str
    count: int


class AnatomySchemaRevisionResponse(BaseModel):
    id: str
    name: str
    revision: int
    schema_version: str
    landmarks: list[AnatomyLandmarkDefinition]
    edges: list[AnatomySkeletonEdge]
    groups: list[AnatomyLandmarkGroupResponse]
    expanded_labels: list[str]
    keypoint_count: int
    allows_repeated_labels: bool
    content_hash: str
    legacy_projection: bool = False
    created_at: datetime


class AnatomySchemaDetailResponse(BaseModel):
    id: str
    project_id: str
    name: str
    revisions: list[AnatomySchemaRevisionResponse]
