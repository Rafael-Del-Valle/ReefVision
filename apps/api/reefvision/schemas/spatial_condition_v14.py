"""Source-bound, locally attributed condition observation and decision contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
EvidenceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Phase = Literal["observation", "review", "adjudication"]


class ConditionRubric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_id: ShortText
    version: ShortText
    reference: EvidenceText
    observation_unit: ShortText
    labels: Annotated[tuple[ShortText, ...], Field(min_length=2, max_length=50)]

    @field_validator("labels")
    @classmethod
    def distinct_labels(cls, labels: tuple[str, ...]) -> tuple[str, ...]:
        if len({label.casefold() for label in labels}) != len(labels):
            raise ValueError("Rubric labels must be distinct")
        return labels


class ConditionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric: ConditionRubric
    source_sha256: Sha256
    metadata_revision_id: UUID | None
    observation_unit_id: ShortText
    reference_evidence: EvidenceText
    observer_id: ShortText
    observed_at_utc: AwareDatetime
    label: ShortText
    uncertainty: EvidenceText

    @field_validator("observed_at_utc")
    @classmethod
    def to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def declared_label(self) -> Self:
        if self.label not in self.rubric.labels:
            raise ValueError("Observation label must be in the declared rubric")
        return self


class ConditionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: ShortText
    decision: Literal["agree", "disagree", "inconclusive", "adjudicated"]
    label: ShortText | None = None
    reference_evidence: EvidenceText
    decided_at_utc: AwareDatetime
    uncertainty: EvidenceText

    @field_validator("decided_at_utc")
    @classmethod
    def to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def decision_label(self) -> Self:
        if self.decision in {"disagree", "adjudicated"} and self.label is None:
            raise ValueError("This decision requires a declared rubric label")
        if self.decision in {"agree", "inconclusive"} and self.label is not None:
            raise ValueError("This decision does not take another label")
        return self


class ConditionRevision(BaseModel):
    id: UUID
    project_id: UUID
    asset_id: UUID
    observation_id: UUID
    previous_revision_id: UUID | None
    phase: Phase
    observation: ConditionObservation
    decision: ConditionDecision | None
    resolved_label: str | None
    stale_source_metadata: bool
    reviewer_authenticated: Literal[False] = False
    scientifically_verified: Literal[False] = False
    content_sha256: Sha256
    created_at: datetime


class ConditionReport(BaseModel):
    schema_version: Literal["reefvision-condition-report-1"] = "reefvision-condition-report-1"
    revision_id: UUID
    revisions: list[ConditionRevision]
