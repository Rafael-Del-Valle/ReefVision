"""Typed, source-linked projected geometry candidates; never verified growth data."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from reefvision.domain.ecology_lineage_policy import classify_ecological_unit_level
from reefvision.domain.ecology_physical_units import is_ecological_physical_length_unit
from reefvision.storage.datasets import canonical_json_sha256


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

    @field_validator("identity_revision", "annotation_revision", mode="before")
    @classmethod
    def require_explicit_revision_integer(cls, value: object) -> int:
        """Preserve exact reviewed identity/annotation revision references."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Evidence revision must be a positive JSON integer")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def reject_coerced_projected_values(cls, value: object) -> object:
        """Do not reinterpret booleans or strings as calibrated measurements."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Projected measurement must be a JSON number, not coerced")
        return value

    @field_validator("image_sha256", "annotation_sha256", "calibration_sha256", mode="before")
    @classmethod
    def require_sha256_evidence_digest(cls, value: object) -> str:
        """Reject malformed digests without changing original provenance casing."""
        if not isinstance(value, str):
            raise ValueError("Source SHA-256 must be 64 hexadecimal characters")
        if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
            raise ValueError("Source SHA-256 must be 64 hexadecimal characters")
        return value

    @field_validator("capture_timestamp_utc", mode="before")
    @classmethod
    def require_explicit_capture_timestamp(cls, value: object) -> object:
        """Numeric epochs and date-only strings are not acquisition timestamps."""
        if value is None or isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]", value.strip()):
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

    @staticmethod
    def _linear_unit_syntax(unit: str) -> bool:
        """Require a physical length label, not pixels or arbitrary dimension text.

        This does not authenticate the underlying scale or its scientific review.
        """
        return is_ecological_physical_length_unit(unit)

    @model_validator(mode="after")
    def consistent_geometry_dimension(self) -> EcologyMeasurementCandidate:
        """Preserve linear box dimensions versus squared mask area evidence.

        This does not authenticate calibration, identity, or biological growth.
        """
        if self.annotation_kind == "box":
            if self.metric not in ("box_width", "box_height") or not self._linear_unit_syntax(
                self.unit
            ):
                raise ValueError("Box geometry requires a linear measurement and unit")
        elif (
            self.metric != "mask_projected_area"
            or not self.unit.endswith("^2")
            or not self._linear_unit_syntax(self.unit[:-2])
        ):
            raise ValueError("Mask projected area requires a squared measurement unit")
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

    @field_validator(
        "baseline_image_id",
        "final_image_id",
        "baseline_annotation_evidence_id",
        "final_annotation_evidence_id",
        "baseline_calibration_evidence_id",
        "final_calibration_evidence_id",
        mode="before",
    )
    @classmethod
    def require_nonblank_endpoint_source_ids(cls, value: object) -> str:
        """Saved endpoint changes must retain explicit source-evidence IDs."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Projected endpoint requires nonblank source evidence IDs")
        return value

    @model_validator(mode="after")
    def require_replayable_endpoint_arithmetic(self) -> EcologyProjectedEndpointChange:
        """Fail closed on edited saved-workflow endpoint arithmetic.

        A typed source-linked change is still unverified projected geometry,
        never an approved growth measurement or independent biological unit.
        """
        start = self.baseline_capture_timestamp_utc
        end = self.final_capture_timestamp_utc
        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or end.tzinfo is None
            or end.utcoffset() is None
        ):
            raise ValueError("Projected endpoints require timezone-aware capture times")
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        if start_utc.date() >= end_utc.date():
            raise ValueError("Projected endpoints require distinct ordered UTC sampling dates")
        if self.baseline_image_id == self.final_image_id:
            raise ValueError("Projected endpoints cannot reuse one source image")

        elapsed = (end_utc - start_utc).total_seconds() / 86400.0
        if not math.isclose(self.elapsed_days, elapsed, rel_tol=1e-9, abs_tol=0.0):
            raise ValueError("Projected endpoint elapsed days do not match source times")
        difference = self.final_value - self.baseline_value
        percent = 100 * (difference / self.baseline_value)
        expected: list[tuple[float, float]] = [
            (self.absolute_change, difference),
            (self.percent_change, percent),
        ]
        if self.projected_absolute_change_per_day is not None:
            expected.append((self.projected_absolute_change_per_day, difference / elapsed))
        if self.projected_baseline_percent_change_per_day is not None:
            expected.append((self.projected_baseline_percent_change_per_day, percent / elapsed))
        if any(
            not math.isfinite(derived)
            or not math.isclose(actual, derived, rel_tol=1e-9, abs_tol=1e-12)
            for actual, derived in expected
        ):
            raise ValueError("Projected endpoint arithmetic does not match source values")
        return self


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

    @field_validator("qc_status_counts", mode="before")
    @classmethod
    def require_explicit_qc_histogram(cls, value: object) -> object:
        """Do not coerce saved scientific QC frequencies or invent statuses."""
        valid_statuses = {
            "mixed_units",
            "missing_timestamps",
            "same_day_technical_replicates",
            "reused_image_across_dates",
            "reused_image_content_across_dates",
            "source_capture_conflict",
            "insufficient_dates",
            "date_series_candidate",
            "identity_context_changed",
        }
        if not isinstance(value, dict) or any(
            status not in valid_statuses
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for status, count in value.items()
        ):
            raise ValueError(
                "Ecological candidate report QC status counts must be nonnegative integers"
            )
        return value

    @model_validator(mode="after")
    def require_qc_histogram_totals(self) -> EcologyCandidateReport:
        """A rehashed report cannot claim impossible series or pass totals."""
        if (
            sum(self.qc_status_counts.values())
            != self.date_qc_pass_series_count + self.excluded_series_count
            or self.qc_status_counts.get("date_series_candidate", 0)
            != self.date_qc_pass_series_count
        ):
            raise ValueError("Ecological candidate report QC totals mismatch")
        return self

    @model_validator(mode="after")
    def require_replayable_report_digest(self) -> EcologyCandidateReport:
        """A saved ecological report must match its own canonical summary.

        A digest checks consistency, not the authenticity of the study data.
        """
        values = {
            "algorithm_version": "ecology-candidate-report-0001",
            "project_id": self.project_id,
            "source_input_sha256": self.source_input_sha256,
            "candidate_count": self.candidate_count,
            "source_image_count": self.source_image_count,
            "source_organism_count": self.source_organism_count,
            "declared_experimental_unit_count": self.declared_experimental_unit_count,
            "date_qc_pass_series_count": self.date_qc_pass_series_count,
            "excluded_series_count": self.excluded_series_count,
            "excluded_source_count": self.excluded_source_count,
            "qc_status_counts": dict(sorted(self.qc_status_counts.items())),
        }
        if canonical_json_sha256(values) != self.report_sha256:
            raise ValueError("Ecological candidate report fingerprint mismatch")
        return self


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

    @model_validator(mode="after")
    def require_current_lineage_digests(self) -> EcologyMeasurementCandidatesResponse:
        """A current source contract cannot silently omit one evidence layer.

        Digest shape is an integrity prerequisite, not proof of source ownership,
        calibration accuracy, scientist review, or biological independence.
        """
        if (
            self.source_fingerprint_contract == "ecology-measurement-candidates-0021"
            and not has_complete_ecology_lineage_digests(self)
        ):
            raise ValueError(
                "Current ecological source fingerprint requires four complete lineage digests"
            )
        return self

    @model_validator(mode="after")
    def require_report_source_consistency(self) -> EcologyMeasurementCandidatesResponse:
        """Prevent a rehashed report from misrepresenting saved source rows.

        Historical payloads without a report remain readable. Alternative
        spellings of the same declared unit are counted once for modern
        reports, while legacy literal-label counts remain admissible.
        Neither count authenticates experimental-unit independence.
        """
        report = self.candidate_report
        if report is None:
            return self
        qc_counts: dict[str, int] = {}
        for row in self.sampling_date_qc:
            qc_counts[row.qc_status] = qc_counts.get(row.qc_status, 0) + 1
        declared_units = {
            (row.experimental_unit_type, row.experimental_unit_id)
            for row in self.candidates
            if row.experimental_unit_type and row.experimental_unit_id
        }
        canonical_units = {
            (classify_ecological_unit_level(unit_type) or unit_type, unit_id)
            for unit_type, unit_id in declared_units
        }
        pass_series_count = qc_counts.get("date_series_candidate", 0)
        expected = (
            report.project_id == self.project_id
            and report.source_input_sha256 == self.input_sha256
            and report.candidate_count == len(self.candidates)
            and report.source_image_count == len({row.image_id for row in self.candidates})
            and report.source_organism_count == len({row.organism_key for row in self.candidates})
            and report.declared_experimental_unit_count
            in (
                len(declared_units),
                len(canonical_units),
            )
            and report.date_qc_pass_series_count == pass_series_count
            and report.excluded_series_count == len(self.sampling_date_qc) - pass_series_count
            and report.excluded_source_count == len(self.exclusions)
            and report.qc_status_counts == qc_counts
        )
        if not expected:
            raise ValueError("Ecological candidate report does not match source rows")
        return self

    @model_validator(mode="before")
    @classmethod
    def require_current_payload_fingerprint(cls, raw: Any) -> Any:
        """Hash stored v0021 rows before optional historical fields default.

        This verifies internal artifact integrity, not scientific approval.
        """
        if (
            not isinstance(raw, dict)
            or raw.get("source_fingerprint_contract") != "ecology-measurement-candidates-0021"
        ):
            return raw
        candidates = raw.get("candidates", [])
        if not isinstance(candidates, list):
            return raw
        if raw.get("candidate_count") != len(candidates):
            raise ValueError("Current ecological candidate count differs from source rows")

        def persisted_rows(field: str) -> object:
            rows = raw.get(field, [])
            if not isinstance(rows, list):
                return rows
            return [
                row.model_dump(mode="json") if isinstance(row, BaseModel) else row for row in rows
            ]

        payload = {
            "algorithm_version": "ecology-measurement-candidates-0021",
            "project_id": raw.get("project_id"),
            "registry_history_sha256": raw.get("source_registry_history_sha256"),
            "registry_image_evidence_sha256": raw.get("source_image_evidence_sha256"),
            "registry_annotation_evidence_sha256": raw.get("source_annotation_evidence_sha256"),
            "registry_calibration_evidence_sha256": raw.get("source_calibration_evidence_sha256"),
            "candidates": persisted_rows("candidates"),
            "sampling_date_qc": persisted_rows("sampling_date_qc"),
            "projected_visit_coverage": persisted_rows("projected_visit_coverage"),
            "projected_endpoint_changes": persisted_rows("projected_endpoint_changes"),
            "projected_unit_summaries": persisted_rows("projected_unit_summaries"),
            "projected_population_summaries": persisted_rows("projected_population_summaries"),
            "exclusions": persisted_rows("exclusions"),
        }
        if canonical_json_sha256(payload) != raw.get("input_sha256"):
            raise ValueError("Current ecological candidate source fingerprint mismatch")
        return raw


def has_complete_ecology_lineage_digests(
    response: EcologyMeasurementCandidatesResponse,
) -> bool:
    """Check four SHA-256 digest fields without asserting scientific verification."""
    if response.source_fingerprint_contract is None:
        return False
    return all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None
        for value in (
            response.source_registry_history_sha256,
            response.source_image_evidence_sha256,
            response.source_annotation_evidence_sha256,
            response.source_calibration_evidence_sha256,
        )
    )
