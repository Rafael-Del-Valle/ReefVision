"""Contracts for reviewed two-dimensional coral graphs and growth."""

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

from reefvision.schemas.connected_branch_editing import (
    ConnectedBranchEdgeResponse,
    ConnectedBranchNodeResponse,
)
from reefvision.schemas.measurements import MeasurementCalibrationUpdate
from reefvision.schemas.skeletonization import SkeletonPixelEdit

Identifier = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Reviewer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GapDecision(StrictRequest):
    disposition: Literal["observed_attachment", "occluded", "unknown", "separate_colony"]
    points: list[SkeletonPixelEdit] = Field(min_length=2, max_length=10000)
    reason: Reason


class GraphEdit(StrictRequest):
    kind: Literal["add", "split", "merge", "remove", "correct"]
    branch_ids: list[Identifier] = Field(default_factory=list, max_length=2)
    points: list[SkeletonPixelEdit] = Field(default_factory=list, max_length=25000)
    snap_tolerance_px: float = Field(default=0, ge=0, le=25, allow_inf_nan=False)

    @model_validator(mode="after")
    def operation_arguments(self) -> Self:
        required_branches = {"add": 0, "split": 1, "merge": 2, "remove": 1, "correct": 1}
        if len(self.branch_ids) != required_branches[self.kind] or len(set(self.branch_ids)) != len(
            self.branch_ids
        ):
            raise ValueError("Select the required distinct branches for this operation")
        if (
            (self.kind in {"add", "correct"} and len(self.points) < 2)
            or (self.kind == "split" and len(self.points) != 1)
            or (self.kind in {"merge", "remove"} and self.points)
            or (self.kind != "add" and self.snap_tolerance_px != 0)
        ):
            raise ValueError("Supply the required path or split point for this operation")
        return self


class GraphReview(StrictRequest):
    identity_revision_id: UUID
    analysis_id: UUID
    base_revision_id: UUID | None = None
    decision: Literal["accepted", "rejected"]
    reviewer: Reviewer
    reason: Reason
    observed_at: AwareDatetime
    edit: GraphEdit | None = None
    gaps: list[GapDecision] = Field(default_factory=list, max_length=100)

    @field_validator("observed_at")
    @classmethod
    def normalize_observation_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class BranchSupersession(BaseModel):
    previous_branch_ids: list[str]
    successor_branch_ids: list[str]


class GraphSnapshot(BaseModel):
    method: Literal["image_plane_coral_graph_v1"] = "image_plane_coral_graph_v1"
    organism_key: str
    image_id: str
    image_sha256: str
    mask_annotation_id: str
    mask_revision: int
    mask_sha256: str
    analysis_sha256: str
    analysis_algorithm: str
    analysis_algorithm_version: str
    observed_at: AwareDatetime
    nodes: list[ConnectedBranchNodeResponse]
    edges: list[ConnectedBranchEdgeResponse]
    total_pixels: float = Field(ge=0, allow_inf_nan=False)
    total_physical: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    calibration: MeasurementCalibrationUpdate | None = None
    calibration_sha256: str | None = None
    edit: GraphEdit | None = None
    attached_pixel: SkeletonPixelEdit | None = None
    gaps: list[GapDecision]
    supersession: list[BranchSupersession] = Field(default_factory=list)
    qc: list[str]
    connected: bool
    eligible_for_growth: bool
    source_reviewed: bool


class GraphRecord(BaseModel):
    id: str
    graph_id: str
    project_id: str
    identity_revision_id: str
    analysis_id: str
    revision: int
    supersedes_id: str | None
    decision: Literal["accepted", "rejected"]
    reviewer: str
    reason: str
    created_at: datetime
    content_sha256: str
    snapshot: GraphSnapshot
    current: bool
    stale_reasons: list[str]


class CorrespondenceMatch(StrictRequest):
    status: Literal["matched", "ambiguous", "missing", "occluded", "split", "merge"]
    earlier_branch_ids: list[Identifier] = Field(max_length=100)
    later_branch_ids: list[Identifier] = Field(max_length=100)
    reason: Reason

    @model_validator(mode="after")
    def match_cardinality(self) -> Self:
        earlier, later = len(set(self.earlier_branch_ids)), len(set(self.later_branch_ids))
        if earlier != len(self.earlier_branch_ids) or later != len(self.later_branch_ids):
            raise ValueError("A correspondence row cannot repeat a branch")
        valid = {
            "matched": (earlier, later) == (1, 1),
            "missing": (earlier == 0) != (later == 0),
            "occluded": (earlier == 0) != (later == 0),
            "ambiguous": earlier > 0 and later > 0,
            "split": earlier == 1 and later > 1,
            "merge": earlier > 1 and later == 1,
        }
        if not valid[self.status]:
            raise ValueError("Branch counts disagree with the correspondence status")
        return self


class CorrespondenceReview(StrictRequest):
    earlier_graph_revision_id: UUID
    later_graph_revision_id: UUID
    base_revision_id: UUID | None = None
    matches: list[CorrespondenceMatch] = Field(min_length=1, max_length=1000)
    reviewer: Reviewer
    reason: Reason


class CorrespondenceSnapshot(BaseModel):
    earlier_graph_sha256: str
    later_graph_sha256: str
    matches: list[CorrespondenceMatch]


class CorrespondenceRecord(BaseModel):
    id: str
    project_id: str
    correspondence_id: str
    earlier_graph_revision_id: str
    later_graph_revision_id: str
    supersedes_id: str | None
    revision: int
    reviewer: str
    reason: str
    created_at: datetime
    content_sha256: str
    snapshot: CorrespondenceSnapshot
    stale_reasons: list[str]


class GrowthRequest(StrictRequest):
    correspondence_revision_id: UUID


class GrowthChange(BaseModel):
    earlier_length: float
    later_length: float
    absolute_change: float
    change_per_day: float


class GrowthBranch(BaseModel):
    status: str
    earlier_branch_ids: list[str]
    later_branch_ids: list[str]
    change: GrowthChange | None
    reason: str


class GrowthSnapshot(BaseModel):
    method: Literal["paired_projected_coral_length_v1"] = "paired_projected_coral_length_v1"
    organism_key: str
    correspondence_sha256: str
    earlier_graph_sha256: str
    later_graph_sha256: str
    earlier_observed_at: AwareDatetime
    later_observed_at: AwareDatetime
    elapsed_days: float = Field(gt=0, allow_inf_nan=False)
    unit: str
    total: GrowthChange | None
    branches: list[GrowthBranch]
    limitations: list[str]


class GrowthRecord(BaseModel):
    id: str
    project_id: str
    correspondence_revision_id: str
    content_sha256: str
    created_at: datetime
    snapshot: GrowthSnapshot
    stale_reasons: list[str]
