"""Local monitoring rules, immutable evidence, and explicit alert review."""

from datetime import timedelta
from typing import Annotated, Any, Generic, Literal, Self, TypeVar
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    TypeAdapter,
    field_validator,
    model_validator,
)

from reefvision.domain.scientific_units import UNITS
from reefvision.schemas.scientific_data import SourceKind, utc_timestamp

MAX_MONITORING_WINDOW_SECONDS = 31 * 24 * 60 * 60
MonitoringDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MonitoringKind = Literal["environmental", "biological"]
MonitoringSourceKind = Literal["scientific_record", "reviewed_event_summary"]
AlertKind = Literal["drop", "delay", "drift", "lower_limit", "upper_limit"]
ReviewDecision = Literal["confirmed", "dismissed"]
SourceStatus = Literal["current", "stale"]


class MonitoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LevelLimits(MonitoringModel):
    lower_limit: FiniteFloat | None = None
    upper_limit: FiniteFloat | None = None

    @model_validator(mode="after")
    def ordered_limits(self) -> Self:
        if (
            self.lower_limit is not None
            and self.upper_limit is not None
            and self.lower_limit >= self.upper_limit
        ):
            raise ValueError("The lower limit must be below the upper limit")
        return self


class EnvironmentalMonitoringParameters(LevelLimits):
    cadence_seconds: int = Field(ge=1, le=86400, strict=True)
    max_drift: Annotated[FiniteFloat, Field(gt=0)] | None = None
    max_delay_seconds: Annotated[FiniteFloat, Field(ge=0)] | None = None
    source_kind: SourceKind = "observed"
    source: str | None = Field(default=None, min_length=1, max_length=300)


class BiologicalMonitoringParameters(LevelLimits):
    summary_ids: list[UUID] = Field(min_length=1, max_length=50)
    minimum_effort_seconds: FiniteFloat = Field(default=1, gt=0)

    @field_validator("summary_ids")
    @classmethod
    def distinct_summaries(cls, ids: list[UUID]) -> list[UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("Select each reviewed event summary once")
        return sorted(ids)


class EnvironmentalMonitoringRule(MonitoringModel):
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["environmental"]
    protocol: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    unit: str
    parameters: EnvironmentalMonitoringParameters

    @field_validator("unit")
    @classmethod
    def canonical_unit(cls, unit: str) -> str:
        if unit not in UNITS or unit != UNITS[unit][1]:
            raise ValueError("Select the normalized unit used by scientific records")
        return unit


class BiologicalMonitoringRule(MonitoringModel):
    label: str = Field(min_length=1, max_length=160)
    kind: Literal["biological"]
    protocol: MonitoringDigest
    metric: Literal["confirmed_events_per_minute"]
    unit: Literal["events/min"]
    parameters: BiologicalMonitoringParameters


MonitoringRuleCreate = Annotated[
    EnvironmentalMonitoringRule | BiologicalMonitoringRule, Field(discriminator="kind")
]
_rule_annotation: Any = MonitoringRuleCreate
MONITORING_RULE = TypeAdapter[MonitoringRuleCreate](_rule_annotation)


class EnvironmentalMonitoringRuleRead(EnvironmentalMonitoringRule):
    id: UUID
    project_id: UUID
    rule_sha256: MonitoringDigest
    created_at: AwareDatetime


class BiologicalMonitoringRuleRead(BiologicalMonitoringRule):
    id: UUID
    project_id: UUID
    rule_sha256: MonitoringDigest
    created_at: AwareDatetime


MonitoringRuleRead = Annotated[
    EnvironmentalMonitoringRuleRead | BiologicalMonitoringRuleRead, Field(discriminator="kind")
]
_rule_read_annotation: Any = MonitoringRuleRead
MONITORING_RULE_READ = TypeAdapter[MonitoringRuleRead](_rule_read_annotation)


class MonitoringWindow(MonitoringModel):
    window_start: AwareDatetime
    window_end: AwareDatetime

    _utc = field_validator("window_start", "window_end")(utc_timestamp)

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if (
            not timedelta(0)
            < self.window_end - self.window_start
            <= timedelta(seconds=MAX_MONITORING_WINDOW_SECONDS)
        ):
            raise ValueError("Choose a positive monitoring window no longer than 31 days")
        return self


class MonitoringAssessmentCreate(MonitoringWindow):
    rule_id: UUID
    rule_sha256: MonitoringDigest


class MonitoringSourceReference(MonitoringModel):
    kind: MonitoringSourceKind
    id: UUID
    sha256: MonitoringDigest
    observed_at: AwareDatetime | None = None
    acquired_at: AwareDatetime | None = None
    source: str | None = None
    original_value: FiniteFloat | None = None
    original_unit: str | None = None
    normalized_value: FiniteFloat | None = None
    normalized_unit: str | None = None
    qc: str | None = None


class MonitoringExclusion(MonitoringModel):
    kind: MonitoringSourceKind | Literal["assessment"]
    source_id: UUID | None = None
    observed_at: AwareDatetime | None = None
    session_id: str | None = None
    reason: str


class MonitoringFinding(MonitoringModel):
    kind: AlertKind
    finding_key: str
    detail: str
    source_ids: list[UUID] = Field(default_factory=list)
    observed_at: AwareDatetime | None = None
    value: FiniteFloat | None = None
    threshold: FiniteFloat | None = None
    unit: str | None = None
    missing_slots: int | None = None


class MonitoringEffort(MonitoringModel):
    expected_slots: int | None = None
    observed_slots: int | None = None
    accepted_observations: int | None = None
    coverage_fraction: FiniteFloat | None = None
    accepted_fraction: FiniteFloat | None = None
    valid_duration_s: FiniteFloat | None = None
    confirmed_event_count: int | None = None
    accepted_sessions: int | None = None


class MonitoringBiologicalSession(MonitoringModel):
    summary_id: UUID
    link_revision_id: str
    link_source_sha256: MonitoringDigest
    organism_key: str
    unit_type: str | None
    unit_id: str | None
    video_id: str
    video_sha256: MonitoringDigest
    measurement_sha256: MonitoringDigest
    event_revision_digest: MonitoringDigest
    event_ids: list[str]
    observed_at: AwareDatetime
    frame_start: int
    frame_end: int
    valid_duration_s: FiniteFloat
    confirmed_event_count: int
    unreviewed_count: int
    partial_count: int
    excluded_confirmed_count: int


class MonitoringAssessmentResult(MonitoringWindow):
    schema_version: Literal["monitoring-assessment-0001"] = "monitoring-assessment-0001"
    project_id: UUID
    rule_id: UUID
    rule_sha256: MonitoringDigest
    evidence_sha256: MonitoringDigest
    kind: MonitoringKind
    protocol: str
    metric: str
    unit: str
    estimate: FiniteFloat | None
    effort: MonitoringEffort
    source_refs: list[MonitoringSourceReference]
    exclusions: list[MonitoringExclusion]
    findings: list[MonitoringFinding]
    biological_sessions: list[MonitoringBiologicalSession] = Field(default_factory=list)
    method: str


class MonitoringAssessmentRead(MonitoringWindow):
    id: UUID
    project_id: UUID
    rule_id: UUID
    evidence_sha256: MonitoringDigest
    result_sha256: MonitoringDigest
    result: MonitoringAssessmentResult
    created_at: AwareDatetime
    source_status: SourceStatus
    stale_reasons: list[str] = Field(default_factory=list)


class MonitoringAlertReviewCreate(MonitoringModel):
    expected_revision: int = Field(ge=0, strict=True)
    decision: ReviewDecision
    reason: str = Field(min_length=3, max_length=500)


class MonitoringAlertReviewRead(MonitoringModel):
    id: UUID
    project_id: UUID
    alert_id: UUID
    reviewer: str
    decision: ReviewDecision
    reason: str
    revision: int
    reviewed_at: AwareDatetime


class MonitoringAlertRead(MonitoringModel):
    id: UUID
    project_id: UUID
    assessment_id: UUID
    kind: AlertKind
    finding_key: str
    proposal: MonitoringFinding
    proposal_sha256: MonitoringDigest
    created_at: AwareDatetime
    status: ReviewDecision | Literal["proposed"]
    review_revision: int
    latest_review: MonitoringAlertReviewRead | None = None
    source_status: SourceStatus


_Item = TypeVar("_Item")


class MonitoringPage(MonitoringModel, Generic[_Item]):
    items: list[_Item]
    total: int
    limit: int
    offset: int


MonitoringRulePage = MonitoringPage[MonitoringRuleRead]
MonitoringAssessmentPage = MonitoringPage[MonitoringAssessmentRead]
MonitoringAlertPage = MonitoringPage[MonitoringAlertRead]
MonitoringAlertReviewPage = MonitoringPage[MonitoringAlertReviewRead]
