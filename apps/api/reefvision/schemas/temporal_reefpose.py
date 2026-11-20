"""Contracts for learned ReefPose temporal refinement."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from unicodedata import normalize
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, TypeAdapter, model_validator

TemporalSplit = Literal["train", "validation", "test"]
TemporalKind = Literal["training", "inference", "evaluation"]
ContextMode = Literal["causal", "centered"]
Device = Annotated[str, Field(pattern=r"^(auto|cpu|cuda(?::[0-9]+)?)$")]
Visibility = Literal["visible", "occluded", "out_of_frame", "uncertain", "absent"]


class TemporalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReefPoseSourceGrouping(TemporalRequest):
    """Recording and animal identifiers declared from the researcher's source records."""

    recording_id: str = Field(min_length=1, max_length=200)
    animal_id: str = Field(min_length=1, max_length=200)

    def split_tokens(self) -> list[str]:
        return [
            f"group:{kind}:{normalize('NFKC', identifier).strip().casefold()}"
            for kind, identifier in (("recording", self.recording_id), ("animal", self.animal_id))
        ]


class TemporalSource(TemporalRequest):
    frame_track_id: UUID
    reviewed_track_id: UUID | None = None
    confirm_same_animal: bool = False
    identity_observation_run_id: UUID | None = None
    animal_identity_id: UUID | None = None
    group_key: str | None = Field(default=None, min_length=1, max_length=200)
    grouping: ReefPoseSourceGrouping | None = None
    discontinuity_frames: list[Annotated[int, Field(ge=0)]] = Field(
        default_factory=list, max_length=10000
    )

    @model_validator(mode="after")
    def validate_identity(self) -> TemporalSource:
        if (self.identity_observation_run_id is None) != (self.animal_identity_id is None):
            raise ValueError("Provide a reviewed identity and its association run together")
        if len(set(self.discontinuity_frames)) != len(self.discontinuity_frames):
            raise ValueError("Discontinuity frame indices must be unique")
        if self.reviewed_track_id is not None and not self.confirm_same_animal:
            raise ValueError("Confirm the reviewed landmarks and frame track show the same animal")
        return self


class TemporalDatasetSource(TemporalSource):
    split: TemporalSplit


class TemporalDatasetCreate(TemporalRequest):
    name: str = Field(min_length=1, max_length=200)
    sources: list[TemporalDatasetSource] = Field(min_length=1, max_length=1000)


class TemporalTrainingCreate(TemporalRequest):
    kind: Literal["training"] = "training"
    dataset_id: UUID
    name: str = Field(min_length=1, max_length=200)
    context_mode: ContextMode = "centered"
    window_length: int = Field(default=9, ge=2, le=129)
    channels: int = Field(default=32, ge=4, le=256)
    max_gap_seconds: FiniteFloat | None = Field(default=None, gt=0)
    epochs: int = Field(default=20, ge=1, le=1000)
    batch_size: int = Field(default=32, ge=1, le=512)
    learning_rate: FiniteFloat = Field(default=0.001, gt=0, le=1)
    loss: Literal["smooth_l1", "mse"] = "smooth_l1"
    seed: int = Field(default=1337, ge=0, le=2**32 - 1)
    device: Device = "auto"

    @model_validator(mode="after")
    def validate_window(self) -> TemporalTrainingCreate:
        if self.context_mode == "centered" and self.window_length % 2 == 0:
            raise ValueError("Centered context requires an odd window length of at least 3")
        return self


class TemporalInferenceCreate(TemporalRequest):
    kind: Literal["inference"] = "inference"
    temporal_model_id: UUID
    source: TemporalSource
    chunk_size: int = Field(default=128, ge=1, le=1024)
    device: Device = "auto"


class TemporalAnatomicalEvents(TemporalRequest):
    landmark_a_id: str = Field(min_length=1, max_length=100)
    landmark_b_id: str = Field(min_length=1, max_length=100)
    open_threshold_px: FiniteFloat = Field(gt=0)
    close_threshold_px: FiniteFloat = Field(ge=0)
    minimum_amplitude_px: FiniteFloat = Field(default=0, ge=0)
    minimum_duration_seconds: FiniteFloat = Field(default=0, ge=0)
    maximum_gap_seconds: FiniteFloat = Field(default=0.25, gt=0)
    onset_tolerance_seconds: FiniteFloat = Field(default=0.25, ge=0)
    offset_tolerance_seconds: FiniteFloat = Field(default=0.25, ge=0)

    @model_validator(mode="after")
    def validate_definition(self) -> TemporalAnatomicalEvents:
        if self.landmark_a_id == self.landmark_b_id:
            raise ValueError("Select two distinct anatomical landmarks")
        if self.open_threshold_px <= self.close_threshold_px:
            raise ValueError("The open threshold must exceed the close threshold")
        return self


class TemporalEvaluationCreate(TemporalRequest):
    kind: Literal["evaluation"] = "evaluation"
    dataset_id: UUID
    temporal_model_id: UUID
    chunk_size: int = Field(default=128, ge=1, le=1024)
    device: Device = "auto"
    movement_threshold_px_per_second: FiniteFloat = Field(default=20.0, gt=0)
    bootstrap_samples: int = Field(default=1000, ge=0, le=10000)
    anatomical_events: TemporalAnatomicalEvents | None = None


TemporalRunCreate = Annotated[
    TemporalTrainingCreate | TemporalInferenceCreate | TemporalEvaluationCreate,
    Field(discriminator="kind"),
]
# Pydantic accepts runtime annotated unions in addition to concrete types.
_temporal_run_annotation: Any = TemporalRunCreate
TEMPORAL_RUN_ADAPTER: TypeAdapter[TemporalRunCreate] = TypeAdapter(_temporal_run_annotation)


class TemporalPointRead(BaseModel):
    landmark_id: str
    x: FiniteFloat | None
    y: FiniteFloat | None
    confidence: FiniteFloat | None = None
    visibility: Visibility


class TemporalLandmarkChoice(BaseModel):
    id: str
    name: str


class TemporalDatasetRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    manifest_sha256: str
    schema_hash: str
    frame_model_sha256: str
    source_count: int
    split_counts: dict[str, int]
    frame_lineage_state: str
    landmarks: list[TemporalLandmarkChoice]


class TemporalDatasetDetail(TemporalDatasetRead):
    manifest: dict[str, Any]


class TemporalRunRead(BaseModel):
    id: UUID
    kind: TemporalKind
    job_id: UUID | None
    status: str
    result: dict[str, Any] | None
    error: str | None
    progress_current: int
    progress_total: int
    created_at: datetime
    configuration: dict[str, Any]
    review_revision: int
    identity_run_id: UUID | None
    identity_id: UUID | None
    source_stale: bool = False


class TemporalFrameRead(BaseModel):
    frame_index: int
    timestamp_seconds: FiniteFloat
    frame_points: list[TemporalPointRead] | None
    refined_points: list[TemporalPointRead | None]
    future_frames: int
    future_seconds: FiniteFloat
    review_source: Literal["frame", "refined", "rejected"] | None = None


class TemporalFramePage(BaseModel):
    items: list[TemporalFrameRead]
    offset: int
    limit: int
    total: int


class TemporalLandmarkCorrection(TemporalRequest):
    landmark_id: str = Field(min_length=1, max_length=100)
    x: FiniteFloat = Field(ge=0)
    y: FiniteFloat = Field(ge=0)


class TemporalReviewFrame(TemporalRequest):
    frame_index: int = Field(ge=0)
    source: Literal["frame", "refined", "rejected"]
    corrections: list[TemporalLandmarkCorrection] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_corrections(self) -> TemporalReviewFrame:
        if self.source == "rejected" and self.corrections:
            raise ValueError("A rejected frame cannot contain accepted corrections")
        if len({item.landmark_id for item in self.corrections}) != len(self.corrections):
            raise ValueError("Each landmark may be corrected once per frame")
        return self


class TemporalReviewCreate(TemporalRequest):
    base_revision: int = Field(ge=0)
    confirmed: Literal[True]
    frames: list[TemporalReviewFrame] = Field(min_length=1, max_length=10000)
    note: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def validate_frames(self) -> TemporalReviewCreate:
        if len({item.frame_index for item in self.frames}) != len(self.frames):
            raise ValueError("Each frame may be reviewed once per revision")
        return self


class TemporalReviewRead(BaseModel):
    id: UUID
    revision: int
    identity_run_id: UUID
    identity_id: UUID
    accepted_frame_count: int
    source_stale: bool


class TemporalTrackChoice(BaseModel):
    id: UUID
    video_id: UUID
    video_name: str
    track_number: int
    revision: int
    model_id: UUID | None = None
    schema_hash: str


class TemporalIdentityChoice(BaseModel):
    id: UUID
    run_id: UUID
    video_id: UUID
    name: str
    revision: int


class TemporalFrameModelChoice(BaseModel):
    id: UUID
    name: str
    sha256: str
    schema_hash: str


class TemporalModelChoice(TemporalFrameModelChoice):
    frame_model_sha256: str
    window_length: int
    context_mode: ContextMode


class TemporalInputsRead(BaseModel):
    frame_tracks: list[TemporalTrackChoice]
    reviewed_tracks: list[TemporalTrackChoice]
    identities: list[TemporalIdentityChoice]
    temporal_models: list[TemporalModelChoice]
    frame_models: list[TemporalFrameModelChoice]
    offset: int
    limit: int
    has_more: bool
