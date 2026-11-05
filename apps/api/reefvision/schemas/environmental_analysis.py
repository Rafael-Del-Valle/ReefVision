"""Typed contracts for immutable composite environmental analyses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from reefvision.schemas.scientific_data import ScientificLocation, ScientificModel, utc_timestamp

EnvironmentalAnalysisKind = Literal[
    "lunar_context",
    "tidal_context",
    "event_window",
    "observation_environment_join",
    "lagged_comparison",
    "current_streamline",
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


class EnvironmentalAnalysisValidationResponse(ScientificModel):
    result_id: UUID
    current: bool
    result_sha256: str = Field(min_length=64, max_length=64)
    reasons: list[str]


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


class TidalContextAnalysisRequest(ScientificModel):
    name: str = Field(min_length=1, max_length=200)
    observed_at: datetime
    location: ScientificLocation
    station_id: str = Field(pattern=r"^\d{7}$")
    datum: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9_-]+$")
    max_time_delta_s: float = Field(gt=0, le=86400)
    max_distance_m: float = Field(ge=0, le=100000)

    _utc = field_validator("observed_at")(utc_timestamp)


class EnvironmentalAnalysisSingleResponse(ScientificModel):
    definition: EnvironmentalAnalysisDefinitionResponse
    result: EnvironmentalAnalysisResultResponse


class EventWindowAnalysisRequest(ScientificModel):
    name: str = Field(min_length=1, max_length=200)
    event_definition_id: UUID
    before_s: float = Field(ge=0, le=604800)
    after_s: float = Field(ge=0, le=604800)
    boundary_policy: Literal["inclusive", "exclusive"] = "inclusive"


class ObservationEnvironmentJoinRequest(ScientificModel):
    name: str = Field(min_length=1, max_length=200)
    observation_record_ids: list[UUID] = Field(min_length=1, max_length=500)
    environmental_variable: str = Field(min_length=1, max_length=100)
    max_time_delta_s: float = Field(gt=0, le=604800)
    max_distance_m: float = Field(ge=0, le=100000)
    require_depth_match: bool = False
    max_depth_delta_m: float = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def unique_observations_and_explicit_depth_tolerance(
        self,
    ) -> ObservationEnvironmentJoinRequest:
        if len(set(self.observation_record_ids)) != len(self.observation_record_ids):
            raise ValueError("Observation record identifiers must be unique")
        if not self.require_depth_match and self.max_depth_delta_m != 0:
            raise ValueError("Depth tolerance requires require_depth_match=true")
        return self


class LaggedComparisonAnalysisRequest(ScientificModel):
    name: str = Field(min_length=1, max_length=200)
    join_result_id: UUID
    lags_s: list[int] = Field(min_length=1, max_length=100)

    @field_validator("lags_s")
    @classmethod
    def unique_bounded_lags(cls, values: list[int]) -> list[int]:
        if len(set(values)) != len(values):
            raise ValueError("Lag values must be unique")
        if any(abs(value) > 604800 for value in values):
            raise ValueError("Lag values are limited to plus or minus seven days")
        return values
