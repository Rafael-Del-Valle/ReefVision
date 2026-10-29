"""Contracts for exploratory paired human-model counts; sources are not authenticated."""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.schemas.scientific_provenance import ScientificInputProvenance


class PairedCountObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, max_length=150)
    organism_id: str = Field(min_length=1, max_length=150)
    parent_colony_id: str | None = Field(default=None, max_length=150)
    metric_name: str = Field(min_length=1, max_length=100)
    reference_source_record_id: str = Field(min_length=1, max_length=150)
    model_source_record_id: str = Field(min_length=1, max_length=150)
    reference_count: float = Field(ge=0)
    model_count: float = Field(ge=0)
    experimental_unit_id: str | None = Field(default=None, max_length=150)
    experimental_unit_type: str | None = Field(default=None, max_length=100)

    @field_validator(
        "observation_id",
        "organism_id",
        "parent_colony_id",
        "metric_name",
        "reference_source_record_id",
        "model_source_record_id",
        "experimental_unit_id",
        "experimental_unit_type",
    )
    @classmethod
    def nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Observation identifiers cannot be blank")
        return stripped

    @field_validator("experimental_unit_type")
    @classmethod
    def reject_technical_units(cls, value: str | None) -> str | None:
        return require_ecological_unit_type(value)

    @field_validator("reference_count", "model_count", mode="before")
    @classmethod
    def reject_boolean_counts(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Count values must be numeric, not Boolean")
        if not isinstance(value, (int, float)):
            raise ValueError("Count values must be JSON numbers, not coerced")
        return value

    @field_validator("reference_count", "model_count")
    @classmethod
    def finite_count(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Counts must be finite")
        if not value.is_integer():
            raise ValueError("Paired organism counts must be whole numbers, not fractions")
        return value


class PairedCountComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pairs: list[PairedCountObservation] = Field(min_length=2, max_length=10000)
    reference_kind: Literal["human_observer", "human_consensus"]
    experimental_unit_type: str | None = Field(default=None, max_length=100)

    @field_validator("experimental_unit_type")
    @classmethod
    def nonempty_unit_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Experimental unit type cannot be blank")
        return require_ecological_unit_type(stripped)


class PairedCountDifference(BaseModel):
    observation_id: str
    organism_id: str
    reference_source_record_id: str
    model_source_record_id: str
    reference_count: float
    model_count: float
    signed_difference: float
    absolute_difference: float
    absolute_percent_deviation: float | None
    # Optional for previously persisted unverified comparison artifacts.
    signed_percent_deviation: float | None = None


class PairedCountUnitSummary(BaseModel):
    experimental_unit_id: str
    paired_observation_count: int
    organism_count: int
    # Source-pair frequency is not an independently verified biological sample size.
    observation_counts_by_organism: dict[str, int] = Field(default_factory=dict)
    repeated_pair_count_beyond_first_per_organism: int = Field(default=0, ge=0)
    unequal_pair_counts_within_unit: bool = False
    mean_signed_bias: float
    mean_absolute_error: float
    organism_balanced_mean_signed_bias: float
    organism_balanced_mean_absolute_error: float
    overcount_pair_count: int = Field(default=0, ge=0)
    undercount_pair_count: int = Field(default=0, ge=0)
    exact_match_pair_count: int = Field(default=0, ge=0)
    # Each organism contributes one directional vote from its mean signed count bias.
    # A zero mean can contain opposing errors; it is not an all-images exact match.
    overcount_organism_count: int = Field(default=0, ge=0)
    undercount_organism_count: int = Field(default=0, ge=0)
    balanced_organism_count: int = Field(default=0, ge=0)
    nonzero_reference_count: int = 0
    percent_contributing_organism_count: int = 0
    mean_absolute_percent_deviation: float | None = None
    organism_balanced_mean_absolute_percent_deviation: float | None = None
    mean_signed_percent_deviation: float | None = None
    organism_balanced_mean_signed_percent_deviation: float | None = None


class PairedCountComparisonResponse(BaseModel):
    evidence_level: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"
    review_status: Literal["requires_source_verification"] = "requires_source_verification"
    reference_kind: Literal["human_observer", "human_consensus"]
    analysis_provenance: ScientificInputProvenance
    metric_name: str
    paired_observation_count: int
    observed_organism_count: int = Field(default=0, ge=0)
    observation_counts_by_organism: dict[str, int] = Field(default_factory=dict)
    repeated_pair_count_beyond_first_per_organism: int = Field(default=0, ge=0)
    unequal_pair_counts_across_organisms: bool = False
    nonzero_reference_count: int
    zero_reference_count: int
    mean_signed_bias: float
    mean_absolute_error: float
    mean_absolute_percent_deviation: float | None
    paired_differences: list[PairedCountDifference]
    overcount_pair_count: int = Field(default=0, ge=0)
    undercount_pair_count: int = Field(default=0, ge=0)
    exact_match_pair_count: int = Field(default=0, ge=0)
    # One mean-signed-bias direction per caller-declared organism, not per image.
    overcount_organism_count: int = Field(default=0, ge=0)
    undercount_organism_count: int = Field(default=0, ge=0)
    balanced_organism_count: int = Field(default=0, ge=0)
    # Optional fields preserve deserialization of older saved workflow artifacts.
    mean_signed_percent_deviation: float | None = None
    experimental_unit_type: str | None = None
    declared_independent_unit_count: int | None = None
    cross_unit_shared_parent_colony_ids: list[str] = Field(default_factory=list)
    unit_summaries: list[PairedCountUnitSummary] = Field(default_factory=list)
    unit_balanced_mean_signed_bias: float | None = None
    unit_balanced_mean_absolute_error: float | None = None
    organism_and_unit_balanced_mean_signed_bias: float | None = None
    organism_and_unit_balanced_mean_absolute_error: float | None = None
    unit_balanced_mean_absolute_percent_deviation: float | None = None
    organism_and_unit_balanced_mean_absolute_percent_deviation: float | None = None
    unit_balanced_mean_signed_percent_deviation: float | None = None
    organism_and_unit_balanced_mean_signed_percent_deviation: float | None = None
    percent_contributing_independent_unit_count: int | None = None
    percent_contributing_organism_count: int | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_current_directional_denominators(self) -> Self:
        """Reject forged sample sizes in versioned, persisted paired-count results."""
        if self.analysis_provenance.algorithm_version != "ecology-paired-count-0007":
            # Older artifacts did not persist organism votes; do not invent them.
            return self
        if (
            self.overcount_pair_count
            + self.undercount_pair_count
            + self.exact_match_pair_count
            != self.paired_observation_count
        ):
            raise ValueError("Directional pair counts must match paired observations")
        if (
            self.overcount_organism_count
            + self.undercount_organism_count
            + self.balanced_organism_count
            != self.observed_organism_count
        ):
            raise ValueError("Directional organism counts must match distinct organisms")
        for unit in self.unit_summaries:
            if (
                unit.overcount_pair_count
                + unit.undercount_pair_count
                + unit.exact_match_pair_count
                != unit.paired_observation_count
            ):
                raise ValueError("Directional unit pair counts must match paired observations")
            if (
                unit.overcount_organism_count
                + unit.undercount_organism_count
                + unit.balanced_organism_count
                != unit.organism_count
            ):
                raise ValueError("Directional unit organism counts must match organisms")
        if self.unit_summaries and (
            sum(unit.paired_observation_count for unit in self.unit_summaries)
            != self.paired_observation_count
            or sum(unit.organism_count for unit in self.unit_summaries)
            != self.observed_organism_count
        ):
            raise ValueError("Directional unit totals must match global denominators")
        return self
