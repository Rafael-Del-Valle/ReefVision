"""Contracts for exploratory paired human-model counts; sources are not authenticated."""

from __future__ import annotations

import math
from collections import Counter
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.domain.scientific_mean import finite_descriptive_mean
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
        # Pydantic stores counts as float. Unsafe JSON integers can round
        # silently (2**53 + 1 -> 2**53), while integral JSON floats beyond
        # the same limit cannot reliably represent consecutive organism counts.
        if value > 2**53 - 1:
            raise ValueError("Count values exceed the IEEE-754 safe-integer range")
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
            self.overcount_pair_count + self.undercount_pair_count + self.exact_match_pair_count
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
        # Persisted denominators must agree with actual paired rows, not merely
        # add up to a plausible total after direction labels are swapped.
        if len(self.paired_differences) != self.paired_observation_count:
            raise ValueError("Directional paired rows must match paired observations")
        # Repeated source or observation IDs cannot create additional evidence.
        # This must also hold when a saved typed artifact is read back, not
        # only when the original caller-supplied request is validated.
        observation_ids = [row.observation_id for row in self.paired_differences]
        reference_ids = [row.reference_source_record_id for row in self.paired_differences]
        model_ids = [row.model_source_record_id for row in self.paired_differences]
        if any(
            len(set(identifiers)) != len(identifiers)
            for identifiers in (observation_ids, reference_ids, model_ids)
        ):
            raise ValueError("Directional paired observation and source IDs must be unique")
        if set(reference_ids) & set(model_ids):
            raise ValueError("Directional human and model source IDs must be disjoint")
        # Current artifacts must reconcile derived rows with their raw counts.
        # A forged signed difference could otherwise satisfy every direction tally.
        for row in self.paired_differences:
            values = (
                row.reference_count,
                row.model_count,
                row.signed_difference,
                row.absolute_difference,
            )
            if any(not math.isfinite(value) for value in values):
                raise ValueError("Directional paired values must be finite")
            if row.reference_count < 0 or row.model_count < 0:
                raise ValueError("Directional raw counts must be nonnegative")
            if row.reference_count > 2**53 - 1 or row.model_count > 2**53 - 1:
                raise ValueError("Directional raw counts exceed IEEE-754 safe-integer range")
            if not row.reference_count.is_integer() or not row.model_count.is_integer():
                raise ValueError("Directional raw counts must be whole numbers")
            if row.signed_difference != row.model_count - row.reference_count:
                raise ValueError("Directional signed differences must match raw counts")
            if row.absolute_difference != abs(row.signed_difference):
                raise ValueError("Directional absolute differences must match raw counts")
            if row.reference_count == 0:
                if (
                    row.absolute_percent_deviation is not None
                    or row.signed_percent_deviation is not None
                ):
                    raise ValueError("Directional zero-reference percentages must be null")
                continue
            expected_percent = row.signed_difference / row.reference_count * 100
            if not math.isfinite(expected_percent):
                raise ValueError("Directional paired percentages must be finite")
            if row.absolute_percent_deviation is None or not math.isclose(
                row.absolute_percent_deviation,
                abs(expected_percent),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("Directional absolute percentages must match raw counts")
            if row.signed_percent_deviation is None or not math.isclose(
                row.signed_percent_deviation,
                expected_percent,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("Directional signed percentages must match raw counts")
        observed_directions = (
            sum(row.signed_difference > 0 for row in self.paired_differences),
            sum(row.signed_difference < 0 for row in self.paired_differences),
            sum(row.signed_difference == 0 for row in self.paired_differences),
        )
        if observed_directions != (
            self.overcount_pair_count,
            self.undercount_pair_count,
            self.exact_match_pair_count,
        ):
            raise ValueError("Directional pair counts must match paired differences")
        observed_organisms = Counter(row.organism_id for row in self.paired_differences)
        if (
            dict(observed_organisms) != self.observation_counts_by_organism
            or len(observed_organisms) != self.observed_organism_count
            or self.repeated_pair_count_beyond_first_per_organism
            != self.paired_observation_count - len(observed_organisms)
        ):
            raise ValueError("Directional organism frequencies must match paired differences")
        if self.nonzero_reference_count != sum(
            row.reference_count > 0 for row in self.paired_differences
        ) or self.zero_reference_count != sum(
            row.reference_count == 0 for row in self.paired_differences
        ):
            raise ValueError("Directional reference denominators must match paired differences")
        # Validate the nested biological denominator independently of its totals.
        # A duplicate organism across tanks must not become two replicates.
        if bool(self.unit_summaries) != (self.experimental_unit_type is not None):
            raise ValueError("Directional unit summaries must match declared unit type")
        if self.unit_summaries:
            unit_ids = [unit.experimental_unit_id for unit in self.unit_summaries]
            if len(set(unit_ids)) != len(unit_ids):
                raise ValueError("Directional experimental unit IDs must be unique")
            if self.declared_independent_unit_count != len(unit_ids):
                raise ValueError("Directional independent-unit denominator must match units")
            unit_organism_counts: Counter[str] = Counter()
            for unit in self.unit_summaries:
                observed = unit.observation_counts_by_organism
                if (
                    len(observed) != unit.organism_count
                    or sum(observed.values()) != unit.paired_observation_count
                    or any(count < 1 for count in observed.values())
                ):
                    raise ValueError("Directional unit organism frequencies must match pairs")
                if unit_organism_counts.keys() & observed.keys():
                    raise ValueError("Directional organism cannot span independent units")
                unit_organism_counts.update(observed)
                if (
                    unit.repeated_pair_count_beyond_first_per_organism
                    != unit.paired_observation_count - unit.organism_count
                ):
                    raise ValueError("Directional repeated-image denominator must match unit")
                if unit.unequal_pair_counts_within_unit != (len(set(observed.values())) > 1):
                    raise ValueError("Directional unit image imbalance flag is inconsistent")
            if dict(unit_organism_counts) != self.observation_counts_by_organism:
                raise ValueError("Directional unit membership must match global organisms")
            for field in (
                "overcount_pair_count",
                "undercount_pair_count",
                "exact_match_pair_count",
                "overcount_organism_count",
                "undercount_organism_count",
                "balanced_organism_count",
                "nonzero_reference_count",
            ):
                if sum(getattr(unit, field) for unit in self.unit_summaries) != getattr(
                    self, field
                ):
                    raise ValueError(f"Directional unit {field} must match global totals")
            if self.percent_contributing_independent_unit_count != sum(
                unit.nonzero_reference_count > 0 for unit in self.unit_summaries
            ):
                raise ValueError("Directional percent-eligible unit count is inconsistent")
            if self.percent_contributing_organism_count != sum(
                unit.percent_contributing_organism_count for unit in self.unit_summaries
            ):
                raise ValueError("Directional percent-eligible organism count is inconsistent")
        for unit in self.unit_summaries:
            if (
                unit.overcount_pair_count + unit.undercount_pair_count + unit.exact_match_pair_count
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

        # Recompute published means from the persisted paired evidence. A
        # plausible direction histogram cannot authorize fabricated averages.
        # Use the same overflow-safe scientific mean as the producer.
        def require_derived_mean(
            field_name: str,
            values: list[float],
            target: PairedCountComparisonResponse | PairedCountUnitSummary = self,
        ) -> None:
            expected = finite_descriptive_mean(values) if values else None
            actual = getattr(target, field_name)
            if (expected is None and actual is not None) or (
                expected is not None
                and (
                    actual is None
                    or not math.isfinite(actual)
                    or not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
                )
            ):
                raise ValueError(f"Directional {field_name} does not match source means")

        grouped_rows: dict[str, list[PairedCountDifference]] = {
            organism: [] for organism in observed_organisms
        }
        for row in self.paired_differences:
            grouped_rows[row.organism_id].append(row)

        # A tank's summary must agree with its own organism rows, not just
        # with totals from other tanks. Otherwise swapping unit-level errors
        # can preserve every global denominator and mean.
        for unit in self.unit_summaries:
            by_organism = {
                organism: grouped_rows[organism]
                for organism in sorted(unit.observation_counts_by_organism)
            }
            rows = [row for group in by_organism.values() for row in group]
            if len(rows) != unit.paired_observation_count:
                raise ValueError("Directional unit rows must match organism membership")
            if (
                sum(row.signed_difference > 0 for row in rows),
                sum(row.signed_difference < 0 for row in rows),
                sum(row.signed_difference == 0 for row in rows),
            ) != (
                unit.overcount_pair_count,
                unit.undercount_pair_count,
                unit.exact_match_pair_count,
            ):
                raise ValueError("Directional unit pair votes must match source rows")
            organism_biases = [
                finite_descriptive_mean(row.signed_difference for row in group)
                for group in by_organism.values()
            ]
            organism_errors = [
                finite_descriptive_mean(row.absolute_difference for row in group)
                for group in by_organism.values()
            ]
            if (
                sum(bias > 0 for bias in organism_biases),
                sum(bias < 0 for bias in organism_biases),
                sum(bias == 0 for bias in organism_biases),
            ) != (
                unit.overcount_organism_count,
                unit.undercount_organism_count,
                unit.balanced_organism_count,
            ):
                raise ValueError("Directional unit organism votes must match source rows")

            def eligible(values: list[float | None]) -> list[float]:
                return [value for value in values if value is not None]

            absolute_percents = eligible([row.absolute_percent_deviation for row in rows])
            signed_percents = eligible([row.signed_percent_deviation for row in rows])
            organism_absolute_percents = [
                finite_descriptive_mean(values)
                for group in by_organism.values()
                if (values := eligible([row.absolute_percent_deviation for row in group]))
            ]
            organism_signed_percents = [
                finite_descriptive_mean(values)
                for group in by_organism.values()
                if (values := eligible([row.signed_percent_deviation for row in group]))
            ]
            if unit.nonzero_reference_count != len(
                absolute_percents
            ) or unit.percent_contributing_organism_count != len(organism_absolute_percents):
                raise ValueError("Directional unit percentage denominators must match rows")
            for field_name, values in (
                ("mean_signed_bias", [row.signed_difference for row in rows]),
                ("mean_absolute_error", [row.absolute_difference for row in rows]),
                ("organism_balanced_mean_signed_bias", organism_biases),
                ("organism_balanced_mean_absolute_error", organism_errors),
                ("mean_absolute_percent_deviation", absolute_percents),
                ("organism_balanced_mean_absolute_percent_deviation", organism_absolute_percents),
                ("mean_signed_percent_deviation", signed_percents),
                ("organism_balanced_mean_signed_percent_deviation", organism_signed_percents),
            ):
                require_derived_mean(field_name, values, unit)

        global_organism_biases = [
            finite_descriptive_mean(row.signed_difference for row in grouped_rows[organism])
            for organism in sorted(grouped_rows)
        ]
        if (
            sum(bias > 0 for bias in global_organism_biases),
            sum(bias < 0 for bias in global_organism_biases),
            sum(bias == 0 for bias in global_organism_biases),
        ) != (
            self.overcount_organism_count,
            self.undercount_organism_count,
            self.balanced_organism_count,
        ):
            raise ValueError("Directional global organism votes must match source rows")
        if self.unequal_pair_counts_across_organisms != (len(set(observed_organisms.values())) > 1):
            raise ValueError("Directional global repeated-image imbalance is inconsistent")

        for field_name, values in (
            ("mean_signed_bias", [row.signed_difference for row in self.paired_differences]),
            ("mean_absolute_error", [row.absolute_difference for row in self.paired_differences]),
            (
                "mean_absolute_percent_deviation",
                [
                    row.absolute_percent_deviation
                    for row in self.paired_differences
                    if row.absolute_percent_deviation is not None
                ],
            ),
            (
                "mean_signed_percent_deviation",
                [
                    row.signed_percent_deviation
                    for row in self.paired_differences
                    if row.signed_percent_deviation is not None
                ],
            ),
        ):
            require_derived_mean(field_name, values)
        for field_name, unit_field in (
            ("unit_balanced_mean_signed_bias", "mean_signed_bias"),
            ("unit_balanced_mean_absolute_error", "mean_absolute_error"),
            (
                "organism_and_unit_balanced_mean_signed_bias",
                "organism_balanced_mean_signed_bias",
            ),
            (
                "organism_and_unit_balanced_mean_absolute_error",
                "organism_balanced_mean_absolute_error",
            ),
            (
                "unit_balanced_mean_absolute_percent_deviation",
                "mean_absolute_percent_deviation",
            ),
            (
                "organism_and_unit_balanced_mean_absolute_percent_deviation",
                "organism_balanced_mean_absolute_percent_deviation",
            ),
            ("unit_balanced_mean_signed_percent_deviation", "mean_signed_percent_deviation"),
            (
                "organism_and_unit_balanced_mean_signed_percent_deviation",
                "organism_balanced_mean_signed_percent_deviation",
            ),
        ):
            require_derived_mean(
                field_name,
                [
                    value
                    for unit in self.unit_summaries
                    if (value := getattr(unit, unit_field)) is not None
                ],
            )
        return self
