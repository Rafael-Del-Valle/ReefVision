"""Typed requests and immutable reports for scientific model comparisons."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from reefvision.schemas.reefpose_validation import Contract, Digest

Icc = Literal["A,1", "C,1"]
Limit = tuple[float, float]


class ComparisonRequest(Contract):
    source_job_ids: list[UUID] = Field(min_length=1, max_length=2)
    metric: Literal["event_count", "measurement"]
    name: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    icc: Icc | None = None
    independent_groups: bool = False
    homoscedastic_normal_differences: bool = False
    bootstrap_seed: int = 20261114

    @model_validator(mode="after")
    def require_comparable_units(self) -> Self:
        if len(set(self.source_job_ids)) != len(self.source_job_ids):
            raise ValueError("Choose distinct completed scoring reports")
        if (self.metric == "measurement") != (self.unit is not None):
            raise ValueError("Continuous measurement comparisons require a unit")
        return self


class PairedValue(Contract):
    video_id: UUID
    group_id: str
    individual_id: str
    frame: int | None = None
    start_s: float | None = None
    end_s: float | None = None
    reference: float
    estimate: float


class ExcludedValue(Contract):
    video_id: UUID
    individual_id: str
    source_job_id: UUID
    frame: int | None = None
    start_s: float | None = None
    reason: str


class AgreementStatistics(Contract):
    sample_count: int
    independent_groups: int
    zero_reference_count: int
    bias: float
    mean_absolute_error: float
    mean_absolute_percentage_error: float | None
    mean_signed_percentage_error: float | None
    limits_of_agreement: Limit | None
    icc: float | None
    bias_ci95: Limit | None
    mae_ci95: Limit | None


class ModelAgreement(Contract):
    source_job_id: UUID
    source_result_sha256: Digest
    model_id: UUID
    checkpoint_sha256: Digest
    model_name: str
    pairs: list[PairedValue]
    statistics: AgreementStatistics


class PairedModelDifference(Contract):
    sample_count: int
    independent_groups: int
    absolute_error_change: float
    absolute_error_change_ci95: Limit | None


class ComparisonSnapshot(Contract):
    method: Literal["reefvision-heldout-agreement-v1"] = "reefvision-heldout-agreement-v1"
    data_kind: Literal["synthetic", "biological"]
    reference_id: UUID
    reference_sha256: Digest
    rater_id: str
    reference_kind: Literal["held_out_human_reference"] = "held_out_human_reference"
    configuration_sha256: Digest
    options: ComparisonRequest
    software_version: str
    models: list[ModelAgreement]
    pairing: PairedModelDifference | None
    exclusions: list[ExcludedValue]
    limitations: list[str]


class LocalSource(Contract):
    job_id: UUID
    result_sha256: Digest


class ComparisonRecord(Contract):
    id: UUID
    project_id: UUID
    content_sha256: Digest
    snapshot: ComparisonSnapshot
    local_sources: list[LocalSource]
    source_id_map: dict[str, str] = Field(default_factory=dict)
    stale: bool = False
