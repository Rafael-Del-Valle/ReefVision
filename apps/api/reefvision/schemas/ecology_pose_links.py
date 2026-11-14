"""Reviewed organism-to-pose link requests and immutable evidence snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Frame = Annotated[int, Field(ge=0)]
LinkState = Literal["current", "stale", "unlinked", "superseded"]


class PoseLinkReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    confirm: Literal[True]
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=500)


class PoseLinkCreate(PoseLinkReview):
    organism_revision_id: UUID
    association_run_id: UUID
    animal_identity_id: UUID
    expected_identity_run_revision: int = Field(ge=1)
    frame_start: Frame
    frame_end: Frame
    expected_pose_schema_sha256: Digest | None = None
    measurement_series_ids: list[UUID] = Field(default_factory=list, max_length=100)
    event_revision_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_scope(self) -> PoseLinkCreate:
        if self.frame_end < self.frame_start:
            raise ValueError("Link start frame must precede or equal its end frame")
        if len(set(self.measurement_series_ids)) != len(self.measurement_series_ids):
            raise ValueError("Measurement series selections must be unique")
        if len(set(self.event_revision_ids)) != len(self.event_revision_ids):
            raise ValueError("Event revision selections must be unique")
        return self


class PoseLinkCorrection(PoseLinkCreate):
    expected_revision: int = Field(ge=1)


class PoseLinkUnlink(PoseLinkReview):
    expected_revision: int = Field(ge=1)


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LinkedPoseObservation(EvidenceModel):
    id: str
    observation_series_id: str
    revision: int = Field(ge=1)
    frame_index: Frame
    source_video_track_id: str
    verification_state: Literal["scientist_confirmed", "scientist_verified"]


class LinkedPoseMeasurement(EvidenceModel):
    id: str
    run_id: str
    definition_id: str
    name: str
    series_sha256: Digest
    result_sha256: Digest


class LinkedPoseEvent(EvidenceModel):
    id: str
    event_series_id: str
    run_id: str
    measurement_series_id: str
    revision: int = Field(ge=1)
    start_frame: Frame
    end_frame: Frame | None
    after_sha256: Digest


class PoseLinkSource(EvidenceModel):
    schema_version: Literal["ecology-pose-link-source-v1"] = "ecology-pose-link-source-v1"
    video_id: str
    video_sha256: Digest
    video_revision: int = Field(ge=1)
    pose_schema_id: str
    pose_schema_revision: int = Field(ge=1)
    pose_schema_sha256: Digest
    identity_run_revision: int = Field(ge=1)
    input_manifest_sha256: Digest
    observations: list[LinkedPoseObservation] = Field(min_length=1)
    measurements: list[LinkedPoseMeasurement]
    events: list[LinkedPoseEvent]


class PoseLinkResponse(BaseModel):
    id: UUID
    project_id: UUID
    link_id: UUID
    revision: int
    action: Literal["link", "correct", "unlink"]
    status: LinkState
    stale_reason: str | None
    supersedes_id: UUID | None
    organism_revision_id: UUID
    organism_key: str
    association_run_id: UUID
    animal_identity_id: UUID
    frame_start: Frame
    frame_end: Frame
    source: PoseLinkSource
    source_sha256: Digest
    reviewer: str
    reason: str
    created_at: datetime


class PoseLinkList(BaseModel):
    items: list[PoseLinkResponse]
    total: int
    limit: int
    offset: int
