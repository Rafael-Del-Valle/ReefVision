"""Typed contracts for immutable composite environmental analyses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from reefvision.schemas.scientific_data import ScientificModel, utc_timestamp

EnvironmentalAnalysisKind = Literal[
    "lunar_context",
    "tidal_context",
    "event_window",
    "observation_environment_join",
    "lagged_comparison",
]


class EnvironmentalAnalysisDefinitionResponse(ScientificModel):
    id: UUID
    project_id: UUID
    analysis_kind: EnvironmentalAnalysisKind
    name: str
    configuration: dict[str, Any]
    calculation_version: str
    definition_sha256: str = Field(min_length=64, max_length=64)
    created_at: datetime


class EnvironmentalAnalysisDefinitionPage(ScientificModel):
    items: list[EnvironmentalAnalysisDefinitionResponse]
    total: int


class EnvironmentalAnalysisResultResponse(ScientificModel):
    id: UUID
    project_id: UUID
    definition_id: UUID
    analysis_kind: EnvironmentalAnalysisKind
    observed_at: datetime
    payload: dict[str, Any]
    input_snapshot: dict[str, Any]
    source_record_ids: list[UUID]
    source_analysis_result_ids: list[UUID]
    quality_control: dict[str, Any]
    uncertainty: dict[str, Any] | None
    content_sha256: str = Field(min_length=64, max_length=64)
    workflow_run_id: UUID | None
    workflow_node_run_id: UUID | None
    created_at: datetime


class EnvironmentalAnalysisResultPage(ScientificModel):
    items: list[EnvironmentalAnalysisResultResponse]
    total: int


class LunarAnalysisBatchRequest(ScientificModel):
    name: str = Field(min_length=1, max_length=200)
    observed_at: list[datetime] = Field(min_length=1, max_length=500)

    @field_validator("observed_at")
    @classmethod
    def normalize_unique_supported_instants(cls, values: list[datetime]) -> list[datetime]:
        normalized = [utc_timestamp(value) for value in values]
        if any(not 1900 <= value.year <= 2100 for value in normalized):
            raise ValueError("Low-precision lunar calculation supports 1900-2100 UTC")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Lunar analysis timestamps must be unique UTC instants")
        return normalized


class LunarAnalysisBatchResponse(ScientificModel):
    definition: EnvironmentalAnalysisDefinitionResponse
    results: list[EnvironmentalAnalysisResultResponse]
