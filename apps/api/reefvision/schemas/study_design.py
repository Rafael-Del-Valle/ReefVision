"""Reviewed experimental-design declarations and immutable evidence receipts."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_analysis import Metric, Text
from reefvision.schemas.ecology_study_assignment import EcologyStudyAssignmentRead, StudyCode
from reefvision.schemas.paired_growth_contrast import (
    Digest,
    PairedGrowthContrastReport,
    PairedGrowthDesign,
)
from reefvision.storage.datasets import canonical_json_sha256

ReviewText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1500)]


class StudyTreatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: StudyCode
    label: Text


class StudyDesignDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Text
    timing: Literal["prospective", "retrospective"]
    reviewed_by: StudyCode
    review_note: ReviewText
    confirm_review: Literal[True]
    contrast: PairedGrowthDesign
    metric: Metric
    method: Literal["paired_growth_contrast"]
    nesting: Literal["parent_colony_within_unit"]
    exclusion_policy: Literal["reviewed_source_exclusions", "no_source_exclusions"]
    exclusion_rule: ReviewText
    organism_keys: Annotated[list[StudyCode], Field(min_length=1, max_length=5000)]
    treatments: Annotated[list[StudyTreatment], Field(max_length=500)]

    @model_validator(mode="after")
    def unique_declarations(self) -> StudyDesignDeclaration:
        if len(self.organism_keys) != len({key.casefold() for key in self.organism_keys}):
            raise ValueError("Enrolled organism keys must be unique")
        if len(self.treatments) != len({row.code.casefold() for row in self.treatments}):
            raise ValueError("Treatment codes must be unique")
        return self


class StudyDesignSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    growth_analysis_id: UUID
    growth_source_sha256: Digest


class StudyDesignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declaration: StudyDesignDeclaration
    growth_analysis_id: UUID | None = None
    growth_source_sha256: Digest | None = None
    supersedes_revision_id: UUID | None = None
    supersedes_sha256: Digest | None = None

    @model_validator(mode="after")
    def require_declared_timing(self) -> StudyDesignCreate:
        if (self.supersedes_revision_id is None) != (self.supersedes_sha256 is None):
            raise ValueError("A prior revision and its digest are required together")
        if self.declaration.timing == "retrospective":
            if self.growth_analysis_id is None or self.growth_source_sha256 is None:
                raise ValueError(
                    "Retrospective designs require a reviewed growth analysis and digest"
                )
        elif self.growth_analysis_id is not None or self.growth_source_sha256 is not None:
            raise ValueError("Freeze the prospective declaration before binding evidence")
        return self


class StudyDesignBind(StudyDesignSource):
    design_sha256: Digest


class StudyDesignReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_revision_id: UUID
    design_sha256: Digest


class StudyDesignRosterMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: UUID
    organism_key: str
    identity_revision: int
    kind: str
    parent_colony_key: str | None
    experimental_unit_type: str
    experimental_unit_id: str
    assignment: EcologyStudyAssignmentRead


class StudyDesignBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID
    source_sha256: Digest
    paired_report: PairedGrowthContrastReport


class StudyDesignSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.5"] = "1.5"
    project_id: UUID
    design_id: UUID
    revision_id: UUID
    supersedes_revision_id: UUID | None
    revision: Annotated[int, Field(ge=1)]
    declared_at: AwareDatetime
    created_at: AwareDatetime
    declaration: StudyDesignDeclaration
    roster: list[StudyDesignRosterMember]
    binding: StudyDesignBinding | None


class StudyDesignReport(BaseModel):
    content_sha256: Digest
    snapshot: StudyDesignSnapshot


class StudyDesignRead(StudyDesignReport):
    id: UUID
    project_id: UUID
    design_id: UUID
    supersedes_revision_id: UUID | None
    revision: int
    created_at: AwareDatetime
    growth_analysis_id: UUID | None
    growth_source_sha256: Digest | None
    source_id_map: dict[str, str]


class StudyDesignPage(BaseModel):
    items: list[StudyDesignRead]
    page: int
    page_size: int
    total: int


def validate_study_design_snapshot(
    snapshot: dict[str, Any], content_sha256: str
) -> StudyDesignSnapshot:
    """Validate archived design and original paired report before following live references."""
    if canonical_json_sha256(snapshot) != content_sha256:
        raise ValidationError("Study design checksum mismatch")
    try:
        parsed = StudyDesignSnapshot.model_validate(snapshot)
    except ValueError as exc:
        raise ValidationError("Invalid study design snapshot") from exc
    if (
        parsed.declared_at > parsed.created_at
        or (parsed.revision == 1) != (parsed.supersedes_revision_id is None)
        or [member.organism_key for member in parsed.roster]
        != sorted(parsed.declaration.organism_keys)
    ):
        raise ValidationError("Study design roster, chronology or revision history is inconsistent")
    if parsed.declaration.timing == "prospective" and (
        parsed.declaration.contrast.baseline_date <= parsed.declared_at.astimezone(UTC).date()
        or (parsed.binding is not None and parsed.revision == 1)
    ):
        raise ValidationError("Prospective design must be frozen before baseline and binding")
    if parsed.binding:
        report = parsed.binding.paired_report
        if (
            report.analysis_id != parsed.binding.analysis_id
            or report.project_id != parsed.project_id
            or report.source_sha256 != parsed.binding.source_sha256
            or report.design != parsed.declaration.contrast
            or report.metric != parsed.declaration.metric
            or {
                (unit.experimental_unit_id, pair.organism_id, pair.identity_revision)
                for unit in report.units
                for pair in unit.organisms
            }
            != {
                (member.experimental_unit_id, member.organism_key, member.identity_revision)
                for member in parsed.roster
            }
            or canonical_json_sha256(report.model_dump(mode="json", exclude={"report_sha256"}))
            != report.report_sha256
        ):
            raise ValidationError("Study design binding differs from its frozen paired report")
    elif parsed.declaration.timing == "retrospective":
        raise ValidationError("Retrospective study design is missing paired evidence")
    return parsed
