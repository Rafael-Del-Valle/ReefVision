"""Versioned local reviewer roles and immutable agreement evidence."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

ReviewRole = Literal["manager", "reviewer", "adjudicator"]
ReviewValue = Literal["usable", "unusable", "uncertain"]
ReviewSlot = Literal["first", "second", "adjudication"]
ReviewSourceType = Literal["image", "queue_item"]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
VALUES: tuple[ReviewValue, ...] = ("usable", "unusable", "uncertain")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewerLabInitialize(Input):
    name: Name


class ReviewerLabRoleCreate(ReviewerLabInitialize):
    role: Literal["reviewer", "adjudicator"]


class ReviewerLabRoleChange(Input):
    base_revision_id: UUID
    active: bool


class ReviewerLabRole(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    member_id: str
    name: str
    role: ReviewRole
    revision: int
    active: bool
    previous_revision_id: str | None
    granted_by_role_revision_id: str | None
    created_at: UtcDatetime


class ReviewerLabStatus(BaseModel):
    initialized: bool
    authority: Literal["local_attribution"] = "local_attribution"


class ReviewerLabSource(Input):
    type: ReviewSourceType
    id: UUID


class ReviewerLabRoundCreate(Input):
    operation_id: UUID
    title: Name
    criterion: Reason
    reviewer_member_ids: tuple[UUID, UUID]
    adjudicator_member_id: UUID
    sources: list[ReviewerLabSource] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def independent_members(self) -> "ReviewerLabRoundCreate":
        if len({*self.reviewer_member_ids, self.adjudicator_member_id}) != 3:
            raise ValueError("Choose two distinct reviewers and a separate adjudicator")
        return self


class ReviewerLabSubject(BaseModel):
    id: str
    image_id: str
    filename: str
    source_sha256: Digest
    annotation_revision: int
    queue_id: str | None = None
    queue_item_id: str | None = None
    queue_input_sha256: Digest | None = None


class ReviewerLabPlan(BaseModel):
    title: Name
    criterion: Reason
    manager: ReviewerLabRole
    reviewers: tuple[ReviewerLabRole, ReviewerLabRole]
    adjudicator: ReviewerLabRole
    subjects: list[ReviewerLabSubject]


class ReviewerLabJudgement(Input):
    operation_id: UUID
    plan_sha256: Digest
    value: ReviewValue
    reason: Reason


class ReviewerLabAdjudication(ReviewerLabJudgement):
    decision_ids: tuple[UUID, UUID]


class ReviewerLabDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    slot: ReviewSlot
    value: ReviewValue
    reason: str
    role_revision_id: str
    created_at: UtcDatetime


class ReviewerLabSubjectView(ReviewerLabSubject):
    own_decision: ReviewerLabDecision | None = None
    paired_decisions: tuple[ReviewerLabDecision, ReviewerLabDecision] | None = None
    resolution: ReviewerLabDecision | None = None
    complete: bool | None = None


class ReviewerLabRound(BaseModel):
    id: str
    title: str
    criterion: str
    plan_sha256: Digest
    report_id: str | None = None
    subjects: list[ReviewerLabSubjectView] = Field(default_factory=list)


class ReviewerLabReportSubject(BaseModel):
    source: ReviewerLabSubject
    first: ReviewerLabDecision
    second: ReviewerLabDecision
    resolution: ReviewerLabDecision | None = None


class ReviewerLabAgreement(BaseModel):
    method: Literal["exact_category_agreement_cohens_kappa_v1"] = (
        "exact_category_agreement_cohens_kappa_v1"
    )
    planned_subjects: int
    paired_subjects: int
    agreements: int
    disagreements: int
    adjudicated_disagreements: int
    matrix: dict[ReviewValue, dict[ReviewValue, int]]
    observed_agreement: float
    cohens_kappa: float | None


class ReviewerLabReportBody(BaseModel):
    schema_version: Literal["reviewer_lab_agreement_v1"] = "reviewer_lab_agreement_v1"
    authority: Literal["local_attribution"] = "local_attribution"
    id: str
    project_id: str
    round_id: str
    plan_sha256: Digest
    plan: ReviewerLabPlan
    sealed_at: UtcDatetime
    sealed_by_role_revision_id: str
    role_revisions: list[ReviewerLabRole]
    agreement: ReviewerLabAgreement
    subjects: list[ReviewerLabReportSubject]


class ReviewerLabReport(ReviewerLabReportBody):
    content_sha256: Digest


class ReviewerLabReportSummary(BaseModel):
    id: str
    title: str
