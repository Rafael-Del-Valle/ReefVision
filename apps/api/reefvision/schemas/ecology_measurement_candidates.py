"""Typed, source-linked projected geometry candidates; never verified growth data."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class EcologyMeasurementCandidate(BaseModel):
    organism_key: str
    identity_revision: int = Field(ge=1)
    parent_colony_key: str | None
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    image_id: str
    image_sha256: str
    annotation_evidence_id: str
    calibration_evidence_id: str
    annotation_kind: Literal["box", "mask"]
    annotation_id: str
    annotation_revision: int = Field(ge=1)
    annotation_sha256: str
    calibration_sha256: str
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    value: float = Field(gt=0, allow_inf_nan=False)
    unit: str
    capture_timestamp_utc: datetime | None
    capture_time_status: Literal["timezone_aware", "missing", "timezone_missing"]
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"

    @field_validator("value", mode="before")
    @classmethod
    def reject_coerced_projected_values(cls, value: object) -> object:
        """Do not reinterpret booleans or strings as calibrated measurements."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Projected measurement must be a JSON number, not coerced")
        return value

    @field_validator("capture_timestamp_utc", mode="before")
    @classmethod
    def require_explicit_capture_timestamp(cls, value: object) -> object:
        """Numeric epochs and date-only strings are not acquisition timestamps."""
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not re.match(
            r"^\\d{4}-\\d{2}-\\d{2}[Tt ]", value.strip()
        ):
            raise ValueError("Capture time must be an explicit ISO 8601 calendar timestamp")
        return value

    @model_validator(mode="after")
    def consistent_capture_time_evidence(self) -> EcologyMeasurementCandidate:
        """Never treat contradictory acquisition metadata as a dated observation."""
        timestamp = self.capture_timestamp_utc
        if self.capture_time_status == "timezone_aware":
            if timestamp is None or timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timezone-aware capture status requires an aware timestamp")
        elif timestamp is not None:
            raise ValueError("Undated capture status cannot carry a timestamp")
        return self


class EcologyMeasurementExclusion(BaseModel):
    calibration_evidence_id: str
    reason: Literal[
        "perspective_transform_requires_review",
        "unsupported_geometry",
        "identity_revision_requires_review",
    ]


class EcologySamplingDateQC(BaseModel):
    """Conservative per-organism/metric UTC-date audit of unverified sources."""

    organism_key: str
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    candidate_count: int = Field(ge=1)
    source_image_ids: list[str]
    units: list[str]
    sampling_dates_utc: list[str]
    duplicate_sampling_dates_utc: list[str]
    missing_timestamp_image_ids: list[str]
    # Optional for backward compatibility with previously persisted artifacts.
    reused_image_ids: list[str] = Field(default_factory=list)
    reused_image_sha256: list[str] = Field(default_factory=list)
    # Optional: old persisted Workflow Builder artifacts remain readable.
    conflicting_source_image_ids: list[str] = Field(default_factory=list)
    conflicting_source_image_sha256: list[str] = Field(default_factory=list)
    qc_status: Literal[
        "mixed_units",
        "missing_timestamps",
        "same_day_technical_replicates",
        "reused_image_across_dates",
        "reused_image_content_across_dates",
        "source_capture_conflict",
        "insufficient_dates",
        "date_series_candidate",
        "identity_context_changed",
    ]
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyProjectedVisitCoverage(BaseModel):
    """Observed linked measurements by UTC date; not a registered visit roster."""

    experimental_unit_type: str | None
    experimental_unit_id: str | None
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    unit: str
    sampling_date_utc: str
    series_organism_keys: list[str]
    measured_organism_keys: list[str]
    no_linked_measurement_organism_keys: list[str]
    undated_organism_keys: list[str]
    same_day_repeat_organism_keys: list[str]
    linked_measurement_count: int = Field(ge=1)
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyProjectedEndpointChange(BaseModel):
    """Descriptive projected-geometry endpoint change; not verified growth."""

    organism_key: str
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    identity_revision: int = Field(ge=1)
    parent_colony_key: str | None
    experimental_unit_type: str | None
    experimental_unit_id: str | None
    unit: str
    baseline_capture_timestamp_utc: datetime
    final_capture_timestamp_utc: datetime
    baseline_image_id: str
    final_image_id: str
    baseline_annotation_evidence_id: str
    final_annotation_evidence_id: str
    baseline_calibration_evidence_id: str
    final_calibration_evidence_id: str
    baseline_value: float = Field(gt=0, allow_inf_nan=False)
    final_value: float = Field(gt=0, allow_inf_nan=False)
    absolute_change: float = Field(allow_inf_nan=False)
    percent_change: float = Field(allow_inf_nan=False)
    elapsed_days: float = Field(gt=0, allow_inf_nan=False)
    # Optional defaults preserve deserialization of previously saved artifacts.
    # These are arithmetic slopes of projected geometry, NOT verified growth.
    projected_absolute_change_per_day: float | None = Field(default=None, allow_inf_nan=False)
    projected_baseline_percent_change_per_day: float | None = Field(
        default=None, allow_inf_nan=False
    )
    observed_timepoint_count: int = Field(ge=2)
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyProjectedUnitSummary(BaseModel):
    """One declared unit, never a verified independent replicate."""

    experimental_unit_type: str | None
    experimental_unit_id: str | None
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    units: list[str]
    organism_keys: list[str]
    complete_organism_keys: list[str]
    incomplete_organism_keys: list[str]
    parent_colony_keys: list[str]
    sampling_windows_utc: list[str]
    unit_status: Literal[
        "candidate",
        "missing_unit_declaration",
        "technical_replicate_unit",
        "mixed_units",
        "incomplete_followup",
        "sampling_window_mismatch",
    ]
    mean_absolute_change: float | None = Field(default=None, allow_inf_nan=False)
    mean_percent_change: float | None = Field(default=None, allow_inf_nan=False)
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyProjectedPopulationSummary(BaseModel):
    """Equal-weight declared-unit summary, not independent-unit verification."""

    experimental_unit_type: str
    metric: Literal["box_width", "box_height", "mask_projected_area"]
    unit: str
    sampling_window_utc: str
    experimental_unit_ids: list[str]
    declared_unit_count: int = Field(ge=1)
    contributing_organism_count: int = Field(ge=1)
    parent_colony_keys: list[str]
    shared_parent_colony_keys: list[str]
    units_missing_parent_colony: list[str]
    mean_unit_absolute_change: float = Field(allow_inf_nan=False)
    mean_unit_percent_change: float = Field(allow_inf_nan=False)
    sample_sd_unit_absolute_change: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    sample_sd_unit_percent_change: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    design_review_blockers: list[
        Literal[
            "independence_not_authenticated",
            "single_declared_unit",
            "shared_parent_colonies",
            "missing_parent_colony",
        ]
    ] = Field(default_factory=list)
    independent_unit_inference_allowed: Literal[False] = False
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyCandidateReport(BaseModel):
    """Deterministic ecological source/effort summary; never verified growth."""

    schema_version: Literal["ecology-candidate-report-0001"] = "ecology-candidate-report-0001"
    project_id: str
    source_input_sha256: str
    candidate_count: int = Field(ge=0)
    source_image_count: int = Field(ge=0)
    source_organism_count: int = Field(ge=0)
    declared_experimental_unit_count: int = Field(ge=0)
    date_qc_pass_series_count: int = Field(ge=0)
    excluded_series_count: int = Field(ge=0)
    excluded_source_count: int = Field(ge=0)
    qc_status_counts: dict[str, int]
    report_sha256: str
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"


class EcologyMeasurementCandidatesResponse(BaseModel):
    schema_version: Literal["ecology-measurement-candidates-0001"] = (
        "ecology-measurement-candidates-0001"
    )
    project_id: str
    source_registry_history_sha256: str | None
    source_calibration_evidence_sha256: str | None
    # Optional additions: older saved Workflow Builder artifacts remain readable.
    source_image_evidence_sha256: str | None = None
    source_annotation_evidence_sha256: str | None = None
    source_fingerprint_contract: (
        Literal[
            "ecology-measurement-candidates-0018",
            "ecology-measurement-candidates-0019",
            "ecology-measurement-candidates-0020",
            "ecology-measurement-candidates-0021",
        ]
        | None
    ) = None
    candidates: list[EcologyMeasurementCandidate] = Field(default_factory=list)
    candidate_count: int = 0
    sampling_date_qc: list[EcologySamplingDateQC] = Field(default_factory=list)
    projected_visit_coverage: list[EcologyProjectedVisitCoverage] = Field(default_factory=list)
    projected_endpoint_changes: list[EcologyProjectedEndpointChange] = Field(default_factory=list)
    projected_unit_summaries: list[EcologyProjectedUnitSummary] = Field(default_factory=list)
    projected_population_summaries: list[EcologyProjectedPopulationSummary] = Field(
        default_factory=list
    )
    exclusions: list[EcologyMeasurementExclusion] = Field(default_factory=list)
    candidate_report: EcologyCandidateReport | None = None
    input_sha256: str
    evidence_level: Literal["linked_unverified"] = "linked_unverified"
    review_gate: Literal["scientist_review_required"] = "scientist_review_required"
