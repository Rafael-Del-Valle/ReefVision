"""Versioned scientific records shared by measurements and environmental context."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from reefvision.domain.scientific_units import UNITS

SourceKind = Literal["observed", "remotely_sensed", "modeled", "derived"]


def utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a UTC offset")
    return value.astimezone(UTC)


class ScientificModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ScientificLocation(ScientificModel):
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    horizontal_uncertainty_m: float | None = Field(default=None, ge=0)


class ScientificPixel(ScientificModel):
    frame: Literal["image_pixels", "video_pixels"]
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class ScientificSubject(ScientificModel):
    image_id: UUID | None = None
    video_id: UUID | None = None
    frame_index: int | None = Field(default=None, ge=0, strict=True)
    track_id: UUID | None = None
    annotation_id: UUID | None = None
    mask_id: UUID | None = None
    prediction_id: UUID | None = None
    model_run_id: UUID | None = None

    @model_validator(mode="after")
    def consistent_media(self) -> ScientificSubject:
        if self.image_id and self.video_id:
            raise ValueError("Choose an image or a video frame; do not mix coordinate frames")
        if (self.frame_index is not None or self.track_id) and self.video_id is None:
            raise ValueError("Video frame and track identifiers require video_id")
        if any((self.annotation_id, self.mask_id, self.prediction_id)) and self.image_id is None:
            raise ValueError("Image object identifiers require image_id")
        if sum(bool(x) for x in (self.annotation_id, self.mask_id, self.prediction_id)) > 1:
            raise ValueError("A record must identify one canonical object")
        return self


class ScientificProvenance(ScientificModel):
    source: str = Field(min_length=1, max_length=300)
    source_url: str | None = Field(default=None, max_length=2000)
    dataset_id: str | None = Field(default=None, max_length=300)
    acquired_at: datetime
    method: str | None = Field(default=None, max_length=200)
    model_version: str | None = Field(default=None, max_length=200)
    processing_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    source_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    spatial_resolution_m: float | None = Field(default=None, gt=0)
    temporal_resolution_s: float | None = Field(default=None, gt=0)

    _utc = field_validator("acquired_at")(utc_timestamp)


class ScientificUncertainty(ScientificModel):
    # Expressed in the original quantity unit, never an absolute temperature.
    value: float = Field(ge=0)
    kind: Literal["standard_deviation", "standard_error", "bound"]
    method: str | None = Field(default=None, max_length=300)


class ScientificRecordCreate(ScientificModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    variable: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    value: float
    unit: str
    observed_at: datetime
    source_kind: SourceKind
    subject: ScientificSubject = Field(default_factory=ScientificSubject)
    location: ScientificLocation | None = None
    pixel: ScientificPixel | None = None
    depth_m: float | None = Field(default=None, ge=0)
    depth_reference: str | None = Field(default=None, max_length=100)
    uncertainty: ScientificUncertainty | None = None
    qc: Literal["unassessed", "accepted", "suspect", "rejected"] = "unassessed"
    qc_flags: list[str] = Field(default_factory=list, max_length=100)
    provenance: ScientificProvenance

    _utc = field_validator("observed_at")(utc_timestamp)

    @field_validator("unit")
    @classmethod
    def supported_unit(cls, value: str) -> str:
        if value not in UNITS:
            raise ValueError("Unsupported unit; provide an explicit supported unit")
        return value

    @model_validator(mode="after")
    def coordinate_and_unit_contract(self) -> ScientificRecordCreate:
        if self.pixel is not None:
            if self.pixel.frame == "image_pixels" and self.subject.image_id is None:
                raise ValueError("Image pixel coordinates require image_id")
            if self.pixel.frame == "video_pixels" and (
                self.subject.video_id is None or self.subject.frame_index is None
            ):
                raise ValueError("Video pixel coordinates require video_id and frame_index")
        if self.depth_m is not None and not self.depth_reference:
            raise ValueError("Depth requires an explicit reference (for example sea_surface)")
        expected = {
            "water_temperature": "temperature",
            "water_potential_temperature": "temperature",
            "current_eastward_velocity": "speed",
            "current_northward_velocity": "speed",
            "current_speed": "speed",
            "practical_salinity": "practical_salinity",
        }.get(self.variable)
        if expected is not None and UNITS[self.unit][0] != expected:
            raise ValueError(f"{self.variable} requires {expected} units")
        return self


class ScientificRecordResponse(ScientificRecordCreate):
    id: UUID
    project_id: UUID
    normalized_value: float
    normalized_unit: str
    normalized_uncertainty: float | None
    calibration_snapshot: dict[str, JsonValue] | None = None
    calibration_sha256: str | None = None
    calibration_current: bool | None = None
    environmental_cache_key: str | None = None
    environmental_snapshot_current: bool | None = None
    content_sha256: str


class ScientificRecordBatch(ScientificModel):
    records: list[ScientificRecordCreate] = Field(min_length=1, max_length=5000)


class ScientificRecordPage(ScientificModel):
    items: list[ScientificRecordResponse]
    total: int
