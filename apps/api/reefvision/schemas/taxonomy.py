"""Versioned local taxonomy and conditional detectability contracts."""

from datetime import UTC, timedelta
from typing import Annotated, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.reviewer_lab_v15 import ReviewRole

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, Field(min_length=1, max_length=150)]
Protocol = Annotated[str, Field(min_length=1, max_length=200)]
Reason = Annotated[str, Field(min_length=3, max_length=1000)]
Effort = Annotated[float, Field(ge=0, le=86400, allow_inf_nan=False)]
Rank = Literal["species", "genus", "family", "order", "class", "phylum", "unranked"]
Decision = Literal["confirmed", "dismissed", "unresolved"]
Outcome = Literal["detected", "not_detected", "unknown", "unobserved"]
Row = TypeVar("Row")


class TaxonomyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaxonomyPage(TaxonomyModel, Generic[Row]):
    items: list[Row]
    total: int
    limit: int
    offset: int


class TaxonomySource(TaxonomyModel):
    kind: Literal["image", "video"]
    id: UUID
    sha256: Digest


class LocalAttribution(TaxonomyModel):
    member_id: UUID
    role_revision_id: UUID
    name: Name
    role: ReviewRole
    authority: Literal["project_local_role"] = "project_local_role"


class IdentityPin(TaxonomyModel):
    id: UUID
    organism_key: str
    revision: int
    kind: Literal["colony", "fragment", "individual"]
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    sha256: Digest


class TaxonProposalCreate(TaxonomyModel):
    identity_revision_id: UUID
    scientific_name: Name
    rank: Rank
    source: TaxonomySource
    reason: Reason


class TaxonProposalSnapshot(TaxonProposalCreate):
    identity: IdentityPin
    author: LocalAttribution
    proposed_at: AwareDatetime


class TaxonProposalRead(TaxonomyModel):
    id: UUID
    project_id: UUID
    proposal: TaxonProposalSnapshot
    proposal_sha256: Digest
    state: Literal["proposed", "confirmed", "dismissed", "unresolved"]
    review_revision: int


class TaxonReviewCreate(TaxonomyModel):
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    decision: Decision
    reason: Reason


class TaxonReviewSnapshot(TaxonReviewCreate):
    target_sha256: Digest
    reviewer: LocalAttribution
    reviewed_at: AwareDatetime


class TaxonReviewRead(TaxonomyModel):
    id: UUID
    revision: int
    review_sha256: Digest
    review: TaxonReviewSnapshot


class DetectabilityVisitCreate(TaxonomyModel):
    proposal_id: UUID
    protocol: Protocol
    started_at: AwareDatetime
    effort_seconds: Effort
    outcome: Outcome
    source: TaxonomySource | None = None
    notes: Reason

    @field_validator("started_at")
    @classmethod
    def normalize_time(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_observation_evidence(self) -> Self:
        if self.outcome in ("detected", "not_detected") and (
            self.effort_seconds <= 0 or self.source is None
        ):
            raise ValueError(
                "A detection or non-detection requires positive effort and source evidence"
            )
        if self.outcome == "unobserved" and (self.source is not None or self.effort_seconds != 0):
            raise ValueError("An unobserved visit has zero effort and no observation source")
        return self


class DetectabilityVisitSnapshot(DetectabilityVisitCreate):
    identity: IdentityPin
    proposal_sha256: Digest
    observer: LocalAttribution
    recorded_at: AwareDatetime


class DetectabilityVisitRead(TaxonomyModel):
    id: UUID
    project_id: UUID
    visit: DetectabilityVisitSnapshot
    visit_sha256: Digest
    presence_revision: int
    presence_status: Literal["pending", "confirmed", "dismissed", "unresolved"]


class PresenceReviewCreate(TaxonReviewCreate):
    source: TaxonomySource | None = None

    @model_validator(mode="after")
    def require_reference(self) -> Self:
        if self.decision == "confirmed" and self.source is None:
            raise ValueError("Confirming known presence requires a separate reference source")
        return self


class PresenceReviewSnapshot(TaxonReviewSnapshot):
    source: TaxonomySource | None


class PresenceReviewRead(TaxonomyModel):
    id: UUID
    revision: int
    review_sha256: Digest
    review: PresenceReviewSnapshot


class DetectabilityRequest(TaxonomyModel):
    scientific_name: Name
    rank: Rank
    protocol: Protocol
    unit_type: Annotated[str, Field(min_length=1, max_length=100)]
    minimum_effort_seconds: Annotated[float, Field(gt=0, le=86400, allow_inf_nan=False)]
    window_start: AwareDatetime
    window_end: AwareDatetime

    @field_validator("unit_type")
    @classmethod
    def validate_unit_type(cls, value: str) -> str:
        return require_ecological_unit_type(value) or value

    @field_validator("window_start", "window_end")
    @classmethod
    def normalize_time(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not timedelta() < (self.window_end - self.window_start) <= timedelta(days=3660):
            raise ValueError("Choose a positive survey window of no more than 3,660 days")
        return self


class AssessmentVisit(TaxonomyModel):
    id: UUID
    visit_sha256: Digest
    visit: DetectabilityVisitSnapshot
    proposal: TaxonProposalRead
    taxonomy_review: TaxonReviewRead | None
    presence_review: PresenceReviewRead | None
    exclusion: str | None


class DetectabilityGroup(TaxonomyModel):
    unit_id: str
    eligible_visits: int
    detections: int
    nondetections: int
    effort_seconds: float
    detection_fraction: float | None
    visit_ids: list[UUID]


class DetectionInterval(TaxonomyModel):
    level: Annotated[float, Field(ge=0.95, le=0.95)] = 0.95
    lower: float
    upper: float
    method: Literal["hoeffding_equal_weight_independent_units"] = (
        "hoeffding_equal_weight_independent_units"
    )


class ExcludedVisit(TaxonomyModel):
    visit_id: UUID
    reason: str


class DetectabilityResult(TaxonomyModel):
    schema_version: Literal["known-presence-detectability-0001"] = (
        "known-presence-detectability-0001"
    )
    request: DetectabilityRequest
    method: Literal["equal_weight_mean_of_repeated_unit_detection_fractions"] = (
        "equal_weight_mean_of_repeated_unit_detection_fractions"
    )
    assumptions: list[str]
    status: Literal["estimated", "withheld"]
    withhold_reason: str | None
    estimate: float | None
    confidence_interval: DetectionInterval | None
    independent_groups: int
    total_recorded_visits: int
    eligible_visits: int
    observed_detections: int
    observed_nondetections: int
    included_effort_seconds: float
    groups: list[DetectabilityGroup]
    exclusions: list[ExcludedVisit]
    evidence_sha256: Digest
    visits: list[AssessmentVisit]


class DetectabilityAssessmentRead(TaxonomyModel):
    id: UUID
    project_id: UUID
    result_sha256: Digest
    result: DetectabilityResult
