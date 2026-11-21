"""Public cross-recording appearance contracts."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reefvision.schemas.temporal_reefpose import Device

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AppearanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    operation_id: UUID
    name: str = Field(min_length=1, max_length=160)
    model_id: UUID
    query_observation_id: UUID
    gallery_observation_ids: list[UUID] = Field(min_length=1, max_length=64)
    minimum_gap_seconds: float = Field(gt=0)
    minimum_similarity: float = Field(default=0.85, ge=-1, le=1)
    minimum_margin: float = Field(default=0.05, ge=0, le=2)
    device: Device = "auto"
    reference_id: UUID | None = None
    reference_rater: str | None = Field(default=None, min_length=1, max_length=200)
    maximum_development_false_rate: float = Field(default=0.05, ge=0, le=1)
    maximum_heldout_false_rate: float | None = Field(default=None, ge=0, le=1)
    maximum_heldout_missed_rate: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def distinct_sources(self) -> "AppearanceRequest":
        if self.query_observation_id in self.gallery_observation_ids or len(
            set(self.gallery_observation_ids)
        ) != len(self.gallery_observation_ids):
            raise ValueError("Choose distinct probe and gallery observations")
        if (self.reference_rater is None) != (self.reference_id is None):
            raise ValueError("Select an independent rater and its frozen reference together")
        targets = (self.maximum_heldout_false_rate, self.maximum_heldout_missed_rate)
        if targets != (None, None) and (self.reference_id is None or None in targets):
            raise ValueError("Declare both held-out rate limits with a frozen reference")
        return self


class AppearanceDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_id: UUID
    study_sha256: Digest
    outcome: Literal["same", "different", "uncertain"]
    candidate_observation_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def selected_candidate(self) -> "AppearanceDecisionRequest":
        if self.outcome in {"same", "different"} and self.candidate_observation_id is None:
            raise ValueError("Identify the specific candidate that was reviewed")
        return self


class AppearanceSummary(BaseModel):
    id: UUID
    name: str
    content_sha256: Digest
    created_at: datetime


class AppearanceResult(AppearanceSummary):
    snapshot: dict[str, Any]
    decisions: list[dict[str, Any]]
    resolution: str


class AppearanceObservationOption(BaseModel):
    id: UUID
    video_id: UUID
    filename: str
    frame_index: int
    identity_name: str
    revision: int
