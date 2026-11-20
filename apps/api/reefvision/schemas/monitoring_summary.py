"""Frozen, project-scoped comparisons of reviewed monitoring evidence."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, FiniteFloat, JsonValue, model_validator

from reefvision.schemas.monitoring import (
    MonitoringAlertReviewRead,
    MonitoringDigest,
    MonitoringEffort,
    MonitoringExclusion,
    MonitoringKind,
    MonitoringModel,
    MonitoringSourceReference,
)


class AssessmentSelection(MonitoringModel):
    project_id: UUID
    assessment_id: UUID


class MonitoringSummaryCreate(MonitoringModel):
    selections: list[AssessmentSelection] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def distinct_projects(self) -> Self:
        if len({row.project_id for row in self.selections}) != len(self.selections):
            raise ValueError("Choose one assessment from each distinct project")
        return self


class ComparedAlert(MonitoringModel):
    alert_id: UUID
    kind: str
    proposal_sha256: MonitoringDigest
    status: Literal["proposed", "confirmed", "dismissed"]
    review_revision: int
    latest_review: MonitoringAlertReviewRead | None


class ComparisonReview(MonitoringModel):
    proposed: int
    confirmed: int
    dismissed: int
    alerts: list[ComparedAlert]


class ComparisonUnit(MonitoringModel):
    unit_type: str | None
    unit_id: str | None
    organism_key: str
    video_id: str
    video_sha256: MonitoringDigest
    link_revision_id: str


class ComparisonValues(MonitoringModel):
    estimate: FiniteFloat | None
    method: str
    source_refs: list[MonitoringSourceReference]
    independent_units: list[ComparisonUnit]
    exclusions: list[MonitoringExclusion]
    rule_parameters: dict[str, JsonValue]


class ComparisonRow(AssessmentSelection):
    project_name: str
    rule_id: UUID
    rule_sha256: MonitoringDigest
    kind: MonitoringKind
    protocol: str
    metric: str
    unit: str
    window_start: AwareDatetime
    window_end: AwareDatetime
    evidence_sha256: MonitoringDigest
    result_sha256: MonitoringDigest
    status: Literal["included", "excluded"]
    reasons: list[str]
    effort: MonitoringEffort
    values: ComparisonValues
    review: ComparisonReview


class ComparisonSnapshot(MonitoringModel):
    schema_version: Literal["monitoring-comparison-1.7"] = "monitoring-comparison-1.7"
    reference_project_id: UUID
    rows: list[ComparisonRow] = Field(min_length=2, max_length=20)


class MonitoringSummaryRead(MonitoringModel):
    id: UUID
    project_id: UUID
    created_at: AwareDatetime
    content_sha256: MonitoringDigest
    snapshot: ComparisonSnapshot


class MonitoringSummaryPage(MonitoringModel):
    items: list[MonitoringSummaryRead]
    total: int
