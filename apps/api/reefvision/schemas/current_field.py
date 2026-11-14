"""Typed current-field streamline preview contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from reefvision.schemas.scientific_data import ScientificLocation, ScientificModel, SourceKind


class CurrentFieldStreamlineRequest(ScientificModel):
    scientific_record_ids: list[UUID] = Field(min_length=1, max_length=5000)
    seeds: list[ScientificLocation] = Field(min_length=1, max_length=100)
    step_seconds: float = Field(default=60, gt=0, le=3600)
    max_steps: int = Field(default=1000, ge=1, le=10000, strict=True)
    max_length_m: float = Field(default=100000, gt=0, le=1_000_000)
    stagnation_m_s: float = Field(default=1e-9, ge=0)


class CurrentFieldAnalysisRequest(CurrentFieldStreamlineRequest):
    name: str = Field(min_length=1, max_length=200)


class CurrentFieldPoint(ScientificModel):
    latitude: float
    longitude: float
    speed_m_s: float = Field(ge=0)


class CurrentFieldStreamline(ScientificModel):
    points: list[CurrentFieldPoint]
    termination: Literal[
        "outside_domain",
        "missing_cell",
        "stagnation",
        "max_steps",
        "max_length",
        "polar_limit",
        "nonfinite_step",
    ]
    length_m: float = Field(ge=0)


class CurrentFieldStreamlineResponse(ScientificModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    algorithm_version: Literal["wgs84-stationary-bilinear-rk4-v1"]
    project_id: UUID
    source_record_ids: list[UUID]
    observed_at: datetime
    source_kind: SourceKind
    depth_m: float | None
    depth_reference: str | None
    environmental_cache_key: str | None
    latitudes: list[float]
    longitudes: list[float]
    input_sha256: str = Field(min_length=64, max_length=64)
    streamlines: list[CurrentFieldStreamline]
    methodological_notes: list[str]
