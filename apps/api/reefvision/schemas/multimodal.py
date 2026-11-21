"""A reviewed common frame, calibrated optical index and an explicit acoustic clock."""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

from reefvision.schemas.bioacoustics import UTCAnchor

Name = Annotated[str, Field(min_length=1, max_length=240)]
Note = Annotated[str, Field(min_length=3, max_length=2000)]
Digest = Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
Microseconds = Annotated[int, Field(ge=0, le=86400000000, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Exposure(Contract):
    index_id: UUID
    index_sha256: Digest
    annotation_evidence_id: UUID
    start_utc: AwareDatetime
    end_utc: AwareDatetime
    uncertainty_us: Microseconds
    clock_evidence: Note
    station_grid_offset_xy: tuple[FiniteFloat, FiniteFloat]
    registration_evidence: Note

    @field_validator("start_utc", "end_utc", mode="before")
    @classmethod
    def declared_utc_offset(cls, value: object) -> object:
        return UTCAnchor.require_declared_offset(value)

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.end_utc <= self.start_utc:
            raise ValueError("An exposure ends after its start")
        return self


class Footprint(Contract):
    grid: Name
    station: Name
    bounds_xyxy: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    registration_error_px: Annotated[float, Field(ge=0)]
    maximum_total_error_px: Annotated[float, Field(ge=0)]
    evidence: Note

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        x0, y0, x1, y1 = self.bounds_xyxy
        if min(x0, y0) < 0 or x0 >= x1 or y0 >= y1:
            raise ValueError("Choose a nonempty footprint in the reference grid")
        return self


class MultimodalRequest(Contract):
    operation_id: UUID
    name: Name
    audio_report_id: UUID
    audio_report_sha256: Digest
    event_label: Name
    channel: Annotated[int, Field(ge=0, le=1, strict=True)]
    maximum_time_uncertainty_us: Microseconds
    footprint: Footprint
    exposures: tuple[Exposure, Exposure]
    full_recording_reviewed: bool
    coverage_evidence: Note
    identity_review: Literal["same organism", "different organisms", "uncertain"]
    identity_evidence: Note

    @model_validator(mode="after")
    def distinct(self) -> Self:
        a, b = self.exposures
        if a.index_id == b.index_id or a.annotation_evidence_id == b.annotation_evidence_id:
            raise ValueError("Select two distinct acquisitions and reviewed organism boxes")
        return self


class MultimodalSummary(Contract):
    id: UUID
    name: str
    content_sha256: Digest
    status: Literal["available", "withheld"]
    created_at: datetime


class MultimodalRead(MultimodalSummary):
    snapshot: dict[str, Any]


class MultimodalOption(Contract):
    id: UUID
    label: str
    digest: Digest
