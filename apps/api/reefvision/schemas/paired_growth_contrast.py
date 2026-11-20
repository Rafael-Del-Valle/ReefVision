"""Frozen two-visit paired growth contrast contracts."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    FiniteFloat,
    StringConstraints,
    field_validator,
    model_validator,
)

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.ecology_analysis import Metric, SourceExclusion, Text

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class PairedGrowthDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_date: date
    followup_date: date
    experimental_unit_type: Text
    estimand: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1500)
    ]
    missingness_policy: Literal["complete_unit"]

    @field_validator("baseline_date", "followup_date", mode="before")
    @classmethod
    def require_explicit_date(cls, value: object) -> object:
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Visit dates must be YYYY-MM-DD UTC dates")
        return value

    @field_validator("experimental_unit_type")
    @classmethod
    def validate_unit_type(cls, value: str) -> str:
        require_ecological_unit_type(value)
        return value

    @model_validator(mode="after")
    def require_ordered_dates(self) -> PairedGrowthDesign:
        if self.baseline_date >= self.followup_date:
            raise ValueError("The follow-up UTC date must be later than baseline")
        return self


class PairedGrowthContrastRequest(PairedGrowthDesign):
    source_sha256: Digest


class PairedGrowthRosterIdentity(BaseModel):
    """The identity fields needed to check a reviewed roster and pair its visits."""

    model_config = ConfigDict(from_attributes=True)

    organism_key: str
    revision: int
    parent_colony_key: str | None
    experimental_unit_type: str | None
    experimental_unit_id: str | None


class PairedGrowthOrganism(BaseModel):
    organism_id: str
    identity_revision: int
    parent_colony_id: str | None
    baseline_source_record_id: UUID | None
    followup_source_record_id: UUID | None
    baseline_candidate_ids: list[UUID]
    followup_candidate_ids: list[UUID]
    baseline_value: FiniteFloat | None
    followup_value: FiniteFloat | None
    unit: str | None
    measurement_method: str | None
    difference: FiniteFloat | None
    reason: str | None


class PairedGrowthUnit(BaseModel):
    experimental_unit_id: str
    status: Literal["included", "excluded"]
    reason: str | None
    difference: FiniteFloat | None
    organisms: list[PairedGrowthOrganism]


class PairedGrowthStatistics(BaseModel):
    mean_difference: FiniteFloat | None
    standard_error: FiniteFloat | None
    degrees_of_freedom: int | None
    confidence_interval_95: tuple[FiniteFloat, FiniteFloat] | None
    interval_status: Literal[
        "available",
        "insufficient_complete_units",
        "zero_between_unit_variation",
        "statistics_runtime_unavailable",
        "precision_unavailable",
    ]


class PairedGrowthReportBody(PairedGrowthStatistics):
    analysis_id: UUID
    project_id: UUID
    source_sha256: Digest
    source_method_version: str
    source_reviewed_by: str
    selected_source_record_ids: list[UUID]
    source_exclusions: list[SourceExclusion]
    design: PairedGrowthDesign
    method_version: Literal["paired-growth-contrast-0001"] = "paired-growth-contrast-0001"
    method_reference: str
    assumptions: list[str]
    metric: Metric
    unit: str | None
    measurement_method: str | None
    units: list[PairedGrowthUnit]
    planned_unit_count: int
    included_unit_count: int


class PairedGrowthContrastReport(PairedGrowthReportBody):
    report_sha256: Digest
