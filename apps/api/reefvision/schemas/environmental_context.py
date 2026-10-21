"""Explicit environmental acquisition and lookup bounds."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from reefvision.schemas.scientific_data import (
    ScientificLocation,
    ScientificModel,
    ScientificRecordResponse,
    ScientificSubject,
    SourceKind,
    utc_timestamp,
)


class NOAAImportRequest(ScientificModel):
    station_id: str = Field(pattern=r"^\d{7}$")
    day: date
    offline: bool = False
    subject: ScientificSubject = Field(default_factory=ScientificSubject)


class EnvironmentalImportResponse(ScientificModel):
    items: list[ScientificRecordResponse]
    cache_status: str
    fetched_at: datetime
    expires_at: datetime
    source_url: str
    skipped_missing: int


def all_source_kinds() -> list[SourceKind]:
    return ["observed", "remotely_sensed", "modeled", "derived"]


class EnvironmentalLookup(ScientificModel):
    variable: str = Field(min_length=1, max_length=100)
    location: ScientificLocation
    observed_at: datetime
    max_distance_m: float = Field(ge=0, le=100000)
    max_time_delta_s: float = Field(ge=0, le=604800)
    depth_m: float | None = Field(default=None, ge=0)
    depth_reference: str | None = Field(default=None, max_length=100)
    max_depth_delta_m: float = Field(default=0, ge=0, le=1000)
    source_kinds: list[SourceKind] = Field(default_factory=all_source_kinds, min_length=1)

    _utc = field_validator("observed_at")(utc_timestamp)

    @model_validator(mode="after")
    def explicit_depth_reference(self) -> "EnvironmentalLookup":
        if self.depth_m is not None and not self.depth_reference:
            raise ValueError("Depth lookup requires an explicit depth_reference")
        return self


class EnvironmentalMatch(ScientificModel):
    record: ScientificRecordResponse
    distance_m: float
    time_delta_s: float
    depth_delta_m: float | None
    cache_fetched_at: datetime | None = None
    cache_expires_at: datetime | None = None
    cache_age_s: float | None = None
    offline_available: bool = True


class EnvironmentalLookupResponse(ScientificModel):
    matches: list[EnvironmentalMatch]
    method: str = "bounded_observations_no_interpolation"


ENVIRONMENTAL_VARIABLES = [
    "water_temperature",
    "water_potential_temperature",
    "practical_salinity",
    "current_eastward_velocity",
    "current_northward_velocity",
    "current_speed",
]


class EnvironmentalSubjectLookup(ScientificModel):
    subject: ScientificSubject
    position_record_id: UUID | None = None
    max_distance_m: float = Field(default=1000, ge=0, le=100000)
    max_time_delta_s: float = Field(default=3600, ge=0, le=604800)
    max_depth_delta_m: float = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def requires_media(self) -> "EnvironmentalSubjectLookup":
        if self.subject.image_id is None and self.subject.video_id is None:
            raise ValueError("Choose an image or video/frame subject")
        return self


class EnvironmentalSubjectContext(ScientificModel):
    status: Literal["available", "unavailable", "ambiguous"]
    reason: str | None = None
    subject: ScientificSubject
    positions: list[ScientificRecordResponse]
    position: ScientificRecordResponse | None = None
    matches: dict[str, list[EnvironmentalMatch]] = Field(default_factory=dict)
    method: str = "bounded_observations_no_interpolation"


class EnvironmentalDatasetSummary(ScientificModel):
    cache_key: str
    provider: str
    source_url: str
    record_count: int
    fetched_at: datetime
    expires_at: datetime


class EnvironmentalDatasetPage(ScientificModel):
    items: list[EnvironmentalDatasetSummary]
    total: int


class LocalCurrentSample(ScientificModel):
    observed_at: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    depth_m: float = Field(ge=0, le=11000)
    eastward_velocity_m_s: float | None
    northward_velocity_m_s: float | None

    _utc = field_validator("observed_at")(utc_timestamp)


class LocalCurrentGridImport(ScientificModel):
    dataset_id: str = Field(min_length=1, max_length=300)
    dataset_version: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=300)
    source_kind: Literal["observed", "remotely_sensed", "modeled"]
    acquired_at: datetime
    samples: list[LocalCurrentSample] = Field(min_length=1, max_length=2500)

    _utc = field_validator("acquired_at")(utc_timestamp)


class CurrentVector(ScientificModel):
    eastward_velocity_m_s: float
    northward_velocity_m_s: float
    speed_m_s: float = Field(ge=0)
    direction_deg_true: float | None = Field(default=None, ge=0, lt=360)
    observed_at: datetime
    depth_m: float = Field(ge=0)
    depth_reference: str
    location: ScientificLocation
    source_kind: SourceKind
    source: str
    dataset_id: str
    dataset_version: str
    component_record_ids: list[UUID] = Field(min_length=2, max_length=2)


class CurrentVectorExclusions(ScientificModel):
    unsupported_record: int = Field(default=0, ge=0)
    invalid_metadata_or_unit: int = Field(default=0, ge=0)
    qc_rejected: int = Field(default=0, ge=0)
    superseded_snapshot: int = Field(default=0, ge=0)
    incomplete_pair: int = Field(default=0, ge=0)
    duplicate_component: int = Field(default=0, ge=0)


class CurrentVectorPage(ScientificModel):
    items: list[CurrentVector]
    input_record_count: int = Field(ge=0)
    exclusions: CurrentVectorExclusions = Field(default_factory=CurrentVectorExclusions)
