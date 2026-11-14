"""Typed contracts for immutable pairwise geographic measurements."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeographicPairwiseCalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    start_observation_id: UUID
    end_observation_id: UUID

    @model_validator(mode="after")
    def require_distinct_observations(self) -> GeographicPairwiseCalculateRequest:
        if self.start_observation_id == self.end_observation_id:
            raise ValueError("Pairwise measurement requires two distinct observation IDs")
        return self


class GeographicPairwiseMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["1.1.0"] = "1.1.0"
    algorithm: Literal["reefvision.wgs84-pairwise-geodesic.v1"]
    project_id: UUID
    start_observation_id: UUID
    end_observation_id: UUID
    start_snapshot: dict[str, Any]
    end_snapshot: dict[str, Any]
    start_snapshot_sha256: str = Field(min_length=64, max_length=64)
    end_snapshot_sha256: str = Field(min_length=64, max_length=64)
    coordinate_reference_system: Literal["EPSG:4326"] = "EPSG:4326"
    distance_m: float = Field(ge=0)
    initial_bearing_deg: float | None = Field(default=None, ge=0, lt=360)
    bearing_unavailable_reason: Literal["coincident_locations"] | None = None
    signed_time_delta_s: float | None = None
    absolute_time_delta_s: float | None = Field(default=None, ge=0)
    time_basis: Literal["utc", "same_video_frame_time", "unavailable"]
    time_unavailable_reason: Literal["no_common_absolute_time_basis"] | None = None
    distance_standard_uncertainty_m: float | None = Field(default=None, ge=0)
    bearing_standard_uncertainty_deg: float | None = Field(default=None, ge=0)
    uncertainty_method: Literal["independent_isotropic_first_order"] | None = None
    uncertainty_unavailable_reason: (
        Literal[
            "missing_endpoint_standard_uncertainty",
            "unknown_or_shared_endpoint_correlation",
            "bearing_geometry_ill_conditioned",
            "coincident_locations",
        ]
        | None
    ) = None
    content_sha256: str = Field(min_length=64, max_length=64)
    methodological_notes: list[str]


class GeographicPairwiseSavedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_id: UUID
    result_id: UUID
    definition_sha256: str = Field(min_length=64, max_length=64)
    result_sha256: str = Field(min_length=64, max_length=64)
    workflow_run_id: UUID | None = None
    workflow_node_run_id: UUID | None = None
    measurement: GeographicPairwiseMeasurement


class GeographicPairwiseValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: UUID
    is_current: bool
    reasons: list[str]
    stored_measurement_sha256: str = Field(min_length=64, max_length=64)
    current_measurement_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    validated_at: datetime
