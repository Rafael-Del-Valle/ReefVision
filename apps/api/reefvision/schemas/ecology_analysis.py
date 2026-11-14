"""Selected and scientist-reviewed ecological analysis contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from math import isclose
from typing import Annotated, Any, Literal
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

from reefvision.domain.errors import ValidationError
from reefvision.domain.experimental_unit_policy import (
    require_ecological_unit_id,
    require_ecological_unit_type,
)
from reefvision.schemas.longitudinal_monitoring import (
    ExperimentalUnitSummary,
    LongitudinalChange,
    PopulationUnitSummary,
)
from reefvision.storage.datasets import canonical_json_sha256

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Metric = Literal["box_width", "box_height", "mask_projected_area"]
SourceKind = Literal["growth", "abundance"]


class GrowthSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calibration_evidence_id: UUID
    exclusion_reason: Text | None = None


class GrowthSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["growth"]
    metric: Metric
    sources: list[GrowthSource] = Field(min_length=2, max_length=1000)


class AbundanceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: UUID | None = None
    sample_id: Text
    experimental_unit_type: Text
    experimental_unit_id: Text
    observed_at: AwareDatetime
    surveyed_area_m2: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    exclusion_reason: Text | None = None

    @field_validator("observed_at", mode="before")
    @classmethod
    def explicit_time(cls, value: object) -> object:
        if not isinstance(value, datetime) and (
            not isinstance(value, str) or len(value) < 11 or value[10] not in "Tt "
        ):
            raise ValueError("Survey time must be an explicit timezone-aware timestamp")
        return value

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_design(self) -> AbundanceSource:
        try:
            require_ecological_unit_type(self.experimental_unit_type)
            require_ecological_unit_id(self.experimental_unit_id)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        if self.image_id is None and self.exclusion_reason is None:
            raise ValueError("A missing survey image requires an explicit exclusion reason")
        return self


class AbundanceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["abundance"]
    class_id: UUID
    sources: list[AbundanceSource] = Field(min_length=1, max_length=1000)


Selection = Annotated[GrowthSelection | AbundanceSelection, Field(discriminator="kind")]


class EcologyAnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: Selection
    reviewed_by: Text
    review_note: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
    ]
    confirm_reviewed_selection: Literal[True]
    supersedes_id: UUID | None = None

    @field_validator("confirm_reviewed_selection", mode="before")
    @classmethod
    def explicitly_confirmed(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit confirmation of reviewed evidence is required")
        return value


class SourceExclusion(BaseModel):
    source: str
    reason: str
    source_kind: Literal["organism", "calibration", "unit", "sample"]


class GrowthObservation(BaseModel):
    calibration_evidence_id: UUID
    annotation_evidence_id: UUID
    image_evidence_id: UUID
    identity_id: UUID
    annotation_id: UUID
    annotation_kind: Literal["box", "mask"]
    image_id: UUID
    organism_key: str
    parent_colony_key: str | None
    identity_revision: int
    annotation_revision: int
    image_sha256: str
    annotation_sha256: str
    calibration_sha256: str
    calibration_source: str
    measurement_method: Literal["scalar_image_plane", "reference_plane_homography"]
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    observed_at: AwareDatetime
    value: float = Field(gt=0, allow_inf_nan=False)
    unit: str


class GrowthResult(BaseModel):
    kind: Literal["growth"] = "growth"
    observations: list[GrowthObservation]
    changes: list[LongitudinalChange] = Field(default_factory=list)
    unit_summaries: list[ExperimentalUnitSummary] = Field(default_factory=list)
    population_summaries: list[PopulationUnitSummary] = Field(default_factory=list)
    exclusions: list[SourceExclusion]


class CountAnnotation(BaseModel):
    annotation_id: UUID
    revision: int = Field(ge=1)
    source_type: str
    geometry_sha256: str
    bounds: tuple[float, float, float, float]


class AbundanceVisit(BaseModel):
    image_id: UUID
    image_sha256: str
    annotation_revision: int
    width_px: int
    height_px: int
    captured_at: AwareDatetime | None
    sample_id: str
    experimental_unit_type: str
    experimental_unit_id: str
    observed_at: AwareDatetime
    annotations: list[CountAnnotation]
    count: int = Field(ge=0, strict=True)
    surveyed_area_m2: float | None
    density_per_m2: float | None = Field(allow_inf_nan=False, ge=0)

    @model_validator(mode="after")
    def validate_counts_and_area(self) -> AbundanceVisit:
        if (
            self.count != len(self.annotations)
            or len({row.annotation_id for row in self.annotations}) != self.count
        ):
            raise ValueError("Survey counts must agree with distinct annotation sources")
        if self.surveyed_area_m2 is None:
            if self.density_per_m2 is not None:
                raise ValueError("Survey density requires a surveyed area")
        elif (
            self.surveyed_area_m2 <= 0
            or self.density_per_m2 is None
            or not isclose(self.density_per_m2, self.count / self.surveyed_area_m2)
        ):
            raise ValueError("Survey density does not match its surveyed area and count")
        return self


class AbundanceUnitSummary(BaseModel):
    observed_on: date
    experimental_unit_type: str
    experimental_unit_id: str
    sample_count: int
    excluded_sample_count: int
    total_count: int
    surveyed_area_m2: float | None
    density_per_m2: float | None = Field(allow_inf_nan=False, ge=0)


class AbundanceResult(BaseModel):
    kind: Literal["abundance"] = "abundance"
    class_name: str
    visits: list[AbundanceVisit]
    unit_summaries: list[AbundanceUnitSummary]
    exclusions: list[SourceExclusion]


class EcologyAnalysisSnapshot(BaseModel):
    schema_version: Literal["reviewed-ecology-analysis-0001"] = "reviewed-ecology-analysis-0001"
    method_version: Literal["reviewed-ecology-descriptive-0001"] = (
        "reviewed-ecology-descriptive-0001"
    )
    evidence_level: Literal["scientist_confirmed_project_evidence"] = (
        "scientist_confirmed_project_evidence"
    )
    selection: Selection
    reviewed_by: Text
    review_note: str
    result: Annotated[GrowthResult | AbundanceResult, Field(discriminator="kind")]
    limitations: list[str]

    @model_validator(mode="after")
    def result_matches_selection(self) -> EcologyAnalysisSnapshot:
        if self.selection.kind != self.result.kind:
            raise ValueError("Ecological analysis result kind disagrees with its selection")
        if isinstance(self.selection, GrowthSelection) and isinstance(self.result, GrowthResult):
            selected = {
                row.calibration_evidence_id
                for row in self.selection.sources
                if row.exclusion_reason is None
            }
            observations = {row.calibration_evidence_id: row for row in self.result.observations}
            if not observations.keys() <= selected or len(observations) != len(
                self.result.observations
            ):
                raise ValueError("Growth observations do not match the reviewed source roster")
            for row in self.result.changes:
                matching = [
                    item for item in observations.values() if item.organism_key == row.organism_id
                ]
                matching.sort(key=lambda item: item.observed_at)
                if len(matching) < 2 or (
                    row.metric_name != self.selection.metric
                    or row.initial_value != matching[0].value
                    or row.final_value != matching[-1].value
                    or row.baseline_source_record_id != str(matching[0].calibration_evidence_id)
                    or row.final_source_record_id != str(matching[-1].calibration_evidence_id)
                    or row.first_observed_at != matching[0].observed_at
                    or row.last_observed_at != matching[-1].observed_at
                    or row.observation_count != len(matching)
                ):
                    raise ValueError(
                        "Growth endpoints do not match their selected dated observations"
                    )
        if isinstance(self.selection, AbundanceSelection) and isinstance(
            self.result, AbundanceResult
        ):
            selected_visits = {
                (row.image_id, row.sample_id, row.observed_at)
                for row in self.selection.sources
                if row.image_id is not None and row.exclusion_reason is None
            }
            visits = {(row.image_id, row.sample_id, row.observed_at) for row in self.result.visits}
            if visits != selected_visits or len(visits) != len(self.result.visits):
                raise ValueError("Survey results do not match the reviewed sample visits")
        return self


class EcologyAnalysisRead(BaseModel):
    id: UUID
    project_id: UUID
    supersedes_id: UUID | None
    created_at: AwareDatetime
    content_sha256: str
    stale: bool
    stale_reason: str | None
    source_id_map: dict[str, str]
    snapshot: EcologyAnalysisSnapshot


class EcologyAnalysisPage(BaseModel):
    items: list[EcologyAnalysisRead]
    total: int
    page: int
    page_size: int


def validate_ecology_analysis_snapshot(
    snapshot: dict[str, Any], content_sha256: str
) -> EcologyAnalysisSnapshot:
    if canonical_json_sha256(snapshot) != content_sha256:
        raise ValidationError("Ecological analysis checksum mismatch")
    try:
        return EcologyAnalysisSnapshot.model_validate(snapshot)
    except ValueError as exc:
        raise ValidationError("Invalid ecological analysis snapshot") from exc


def ecology_analysis_source_ids(snapshot: dict[str, Any]) -> set[str]:
    """Return only structural source IDs; free-text/reviewer strings are original evidence."""
    identifiers: set[str] = set()
    selection = snapshot["selection"]
    result = snapshot["result"]
    if selection["kind"] == "growth":
        identifiers.update(row["calibration_evidence_id"] for row in selection["sources"])
        for row in result["observations"]:
            identifiers.update(
                row[key]
                for key in (
                    "calibration_evidence_id",
                    "annotation_evidence_id",
                    "image_evidence_id",
                    "identity_id",
                    "annotation_id",
                    "image_id",
                )
            )
    else:
        identifiers.add(selection["class_id"])
        identifiers.update(row["image_id"] for row in selection["sources"] if row["image_id"])
        for visit in result["visits"]:
            identifiers.update(row["annotation_id"] for row in visit["annotations"])
    return identifiers
