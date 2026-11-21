"""Typed contracts for reviewed annotation count aggregates."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

AggregateSourceKind = Literal["verified_annotations", "verified_masks"]
AggregateGroupingLevel = Literal["image", "image_group_key"]


class AggregateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ComputedAggregateDefinitionCreate(AggregateModel):
    name: str = Field(min_length=1, max_length=200)
    source_kind: AggregateSourceKind
    grouping_level: AggregateGroupingLevel
    label_class_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @field_validator("label_class_ids")
    @classmethod
    def unique_labels(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Label class IDs must be unique")
        return value


class ComputedAggregateDefinitionResponse(ComputedAggregateDefinitionCreate):
    id: UUID
    project_id: UUID
    definition_kind: Literal["annotation_aggregate"] = "annotation_aggregate"
    expression: str
    operation: Literal["count"] = "count"
    output_unit: Literal["count"] = "count"
    formula_version: Literal["reefvision.annotation-aggregate.v1"]
    schema_version: Literal["1.1.0"] = "1.1.0"
    required_review_state: Literal["reviewed"] = "reviewed"
    independence_contract: Literal["one_unit_per_image", "one_unit_per_image_group_key"]
    definition_sha256: str
    created_at: datetime


class ComputedAggregateDefinitionPage(AggregateModel):
    items: list[ComputedAggregateDefinitionResponse]
    total: int


class ComputedAggregateSelection(AggregateModel):
    image_ids: list[UUID] = Field(min_length=1, max_length=500)

    @field_validator("image_ids")
    @classmethod
    def unique_images(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Image IDs must be unique")
        return value


class AggregateClassCount(AggregateModel):
    label_class_id: UUID | None
    label_name: str
    count: int = Field(ge=0)


class AggregateGroup(AggregateModel):
    unit_key: str
    image_ids: list[UUID]
    observation_count: int = Field(ge=0)
    counts_by_class: list[AggregateClassCount]


class ComputedAggregatePreview(AggregateModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    definition_id: UUID
    definition_sha256: str
    source_kind: AggregateSourceKind
    grouping_level: AggregateGroupingLevel
    operation: Literal["count"] = "count"
    required_review_state: Literal["reviewed"] = "reviewed"
    image_count: int = Field(ge=1)
    independent_unit_count: int = Field(ge=1)
    observation_count: int = Field(ge=0)
    mean_per_independent_unit: float = Field(ge=0)
    counts_by_class: list[AggregateClassCount]
    groups: list[AggregateGroup]
    excluded_proposals_by_status: dict[str, int]
    image_snapshot: list[dict[str, JsonValue]]
    observation_snapshot: list[dict[str, JsonValue]]
    evidence_sha256: str


class ComputedAggregateResultResponse(ComputedAggregatePreview):
    id: UUID
    project_id: UUID
    result_kind: Literal["annotation_aggregate"] = "annotation_aggregate"
    definition_name: str
    expression: str
    formula_version: Literal["reefvision.annotation-aggregate.v1"]
    output_unit: Literal["count"] = "count"
    observed_at: datetime
    provenance: dict[str, JsonValue]
    content_sha256: str
    workflow_run_id: UUID | None = None
    workflow_node_run_id: UUID | None = None
    created_at: datetime


class ComputedAggregateResultPage(AggregateModel):
    items: list[ComputedAggregateResultResponse]
    total: int


class ComputedAggregateValidationResponse(AggregateModel):
    result_id: UUID
    current: bool
    saved_evidence_sha256: str
    current_evidence_sha256: str
    reasons: list[str]
