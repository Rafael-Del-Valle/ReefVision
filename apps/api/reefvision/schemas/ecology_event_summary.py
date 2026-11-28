"""Reviewed ecological event-rate report contracts."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from reefvision.schemas.ecology_pose_links import Digest


class EventSessionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_revision_id: UUID
    event_run_id: UUID
    measurement_series_id: UUID
    observed_at: AwareDatetime | None = None


class EventSummaryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=150)
    sessions: list[EventSessionSelection] = Field(min_length=1, max_length=100)
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=500)
    confirm: Literal[True]

    @model_validator(mode="after")
    def unique_sessions(self) -> Self:
        if len({item.link_revision_id for item in self.sessions}) != len(self.sessions):
            raise ValueError("Select one event protocol per reviewed link")
        return self


class ReviewedEventValue(BaseModel):
    id: str
    event_series_id: str
    after_sha256: Digest
    start_frame: int
    end_frame: int
    start_time_s: FiniteFloat
    end_time_s: FiniteFloat
    duration_s: FiniteFloat
    amplitude: FiniteFloat | None


class ValidEventInterval(BaseModel):
    start_frame: int
    end_frame: int
    start_time_s: FiniteFloat
    end_time_s: FiniteFloat


class EventRate(BaseModel):
    confirmed_complete_count: int = Field(ge=0)
    valid_duration_s: Annotated[FiniteFloat, Field(ge=0)]
    confirmed_events_per_minute: FiniteFloat | None


class EventSessionSummary(EventRate):
    link_revision_id: str
    link_source_sha256: Digest
    identity_revision_id: str
    organism_key: str
    unit_type: str | None
    unit_id: str | None
    video_id: str
    video_sha256: Digest
    identity_run_id: str
    animal_identity_id: str
    measurement_run_id: str
    measurement_series_id: str
    measurement_sha256: Digest
    event_run_id: str
    event_revision_digest: Digest
    observed_at: AwareDatetime | None
    frame_start: int
    frame_end: int
    valid_intervals: list[ValidEventInterval]
    invalid_frame_count: int
    partial_count: int
    unreviewed_count: int
    excluded_confirmed_count: int
    amplitude_unit: str
    events: list[ReviewedEventValue]


class EventOrganismSummary(EventRate):
    organism_key: str
    session_count: int
    unit_type: str | None
    unit_id: str | None


class EventUnitSummary(EventRate):
    unit_type: str
    unit_id: str
    organism_count: int


class EventSummarySnapshot(BaseModel):
    method: Literal["reviewed_ecology_event_rate_v1"] = "reviewed_ecology_event_rate_v1"
    evidence_level: Literal["reviewed_scoped_pose_events"] = "reviewed_scoped_pose_events"
    selection: EventSummaryCreate
    protocol_sha256: Digest
    sessions: list[EventSessionSummary]
    organisms: list[EventOrganismSummary]
    units: list[EventUnitSummary]


class EventSummaryRead(BaseModel):
    id: UUID
    project_id: UUID
    created_at: datetime
    content_sha256: Digest
    snapshot: EventSummarySnapshot
    source_id_map: dict[str, str] = Field(default_factory=dict)
    stale_reasons: list[str] = Field(default_factory=list)


class EventSummaryPage(BaseModel):
    items: list[EventSummaryRead]
    total: int
