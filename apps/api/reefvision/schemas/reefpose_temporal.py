"""Contracts for preparing independent event supervision for temporal models."""

from uuid import UUID

from pydantic import Field

from reefvision.schemas.reefpose_validation import (
    Contract,
    Digest,
    EventWindow,
    Key,
    ReferenceEvent,
)


class TemporalClipRequest(Contract):
    measurement_run_id: UUID
    animal_identity_id: UUID
    reference_individual_id: Key


class TemporalDatasetRequest(Contract):
    rater_id: Key
    label: Key
    feature_ids: list[Key] = Field(min_length=1, max_length=8)
    clips: list[TemporalClipRequest] = Field(min_length=1, max_length=32)


class TemporalFrame(Contract):
    frame_index: int
    time_s: float
    window_index: int
    values: list[float | None]
    confidence: list[float | None]
    reference_unobservable: bool
    target: int | None


class TemporalClip(Contract):
    video_id: UUID
    video_sha256: Digest
    group_id: Key
    reference_individual_id: Key
    annotation_sha256: Digest
    measurement_run_id: UUID
    measurement_sha256: Digest
    measurement_input_sha256: Digest
    animal_identity_id: UUID
    identity_run_id: UUID
    identity_run_revision: int
    source_pose_model_id: UUID | None
    source_pose_model_sha256: Digest | None
    series_sha256: list[Digest]
    windows: list[EventWindow]
    events: list[ReferenceEvent]
    frames: list[TemporalFrame]


class TemporalFeature(Contract):
    definition_id: Key
    landmark_ids: list[str]
    formula_version: str
    definition_sha256: Digest
    unit: str


class TemporalDatasetManifest(Contract):
    schema_version: str = "reefpose-temporal-training-1"
    reference_id: UUID
    reference_sha256: Digest
    data_kind: str
    pose_schema_sha256: Digest
    rater_id: Key
    label: Key
    features: list[TemporalFeature]
    clips: list[TemporalClip]


class TemporalDatasetResponse(Contract):
    manifest: TemporalDatasetManifest
    sha256: Digest
