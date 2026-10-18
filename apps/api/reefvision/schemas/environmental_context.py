"""Explicit environmental acquisition and lookup bounds."""

from datetime import date, datetime

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


class EnvironmentalLookupResponse(ScientificModel):
    matches: list[EnvironmentalMatch]
    method: str = "bounded_observations_no_interpolation"
