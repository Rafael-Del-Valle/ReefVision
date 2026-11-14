"""Frozen evidence and count agreement for reviewed static images."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from reefvision.schemas.reefpose_validation import Contract, Digest
from reefvision.schemas.scientific_comparison import Icc, Limit

LineageStatus = Literal["held_out", "exploratory", "overlap"]
CountStatus = Literal[
    "scored",
    "class_not_mapped",
    "output_class_mismatch",
    "inference_failed",
    "prediction_missing",
    "excluded_image",
    "unreviewed_image",
]


class StaticInferenceSettings(Contract):
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    iou_threshold: float = Field(default=0.7, ge=0, le=1)
    device: Literal["auto", "cpu", "cuda"] = "auto"


class StaticComparisonRequest(Contract):
    dataset_version_id: UUID
    model_ids: list[UUID] = Field(min_length=1, max_length=2)
    class_ids: list[UUID] = Field(default_factory=list)
    split: Literal["test", "all"] = "test"
    inference: StaticInferenceSettings = Field(default_factory=StaticInferenceSettings)
    independent_groups: bool = False
    homoscedastic_normal_differences: bool = False
    icc: Icc | None = None
    bootstrap_seed: int = 20261114

    @model_validator(mode="after")
    def disallow_duplicate_identities(self) -> Self:
        if len(set(self.model_ids)) != len(self.model_ids):
            raise ValueError("Choose distinct registered models")
        if len(set(self.class_ids)) != len(self.class_ids):
            raise ValueError("Choose distinct reference classes")
        return self


class StaticClass(Contract):
    id: UUID
    name: str


class StaticDatasetOption(Contract):
    id: UUID
    name: str
    reviewed_count: int
    test_reviewed_count: int
    classes: list[StaticClass]


class StaticModelOption(Contract):
    id: UUID
    name: str
    mapped_class_ids: list[UUID]


class StaticOptions(Contract):
    datasets: list[StaticDatasetOption]
    models: list[StaticModelOption]


class ReferenceAnnotation(Contract):
    id: UUID
    revision: int
    class_id: UUID
    source_model_id: UUID | None = None


class StaticReferenceImage(Contract):
    id: UUID
    name: str
    image_sha256: Digest
    item_sha256: Digest
    group_key: str | None
    split: str
    exclusion: Literal["excluded_image", "unreviewed_image"] | None
    annotations: list[ReferenceAnnotation]


class LineageDataset(Contract):
    id: UUID
    manifest_sha256: Digest
    splits: list[str]


class StaticLineage(Contract):
    status: LineageStatus
    reasons: list[str]
    training_run_ids: list[UUID]
    model_selection_job_ids: list[UUID]
    checkpoint_dependencies: dict[UUID, Digest]
    datasets: list[LineageDataset]
    overlapping_image_ids: list[UUID]


class StaticModelEvidence(Contract):
    id: UUID
    name: str
    checkpoint_sha256: Digest
    provider_name: str
    registration_provider_version: str
    labels: list[str]
    mapping: dict[str, UUID | None]
    lineage: StaticLineage


class StaticEvidence(Contract):
    options: StaticComparisonRequest
    reference_name: str
    reference_sha256: Digest
    classes: list[StaticClass]
    outside_split_image_count: int = 0
    images: list[StaticReferenceImage]
    models: list[StaticModelEvidence]


class StaticPrediction(Contract):
    label: str
    class_index: int | None
    class_id: UUID | None
    confidence: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float]


class StaticClassCount(Contract):
    class_id: UUID
    reference: int = Field(ge=0)
    prediction: int | None = Field(default=None, ge=0)
    status: CountStatus


class StaticImageResult(Contract):
    image_id: UUID
    status: Literal[
        "inferred", "inference_failed", "prediction_missing", "excluded_image", "unreviewed_image"
    ]
    message: str | None = None
    raw_predictions: list[StaticPrediction] = Field(default_factory=list)
    counts: list[StaticClassCount] = Field(default_factory=list)


class StaticStatistics(Contract):
    observation_count: int
    frozen_group_count: int
    independent_group_count: int | None
    ungrouped_observation_count: int
    zero_reference_count: int
    percentage_denominator: int
    bias: float | None
    mean_absolute_error: float | None
    root_mean_squared_error: float | None
    mean_absolute_percentage_error: float | None
    mean_signed_percentage_error: float | None
    limits_of_agreement: Limit | None
    icc: float | None
    bias_ci95: Limit | None
    mae_ci95: Limit | None


class StaticModelResult(Contract):
    model_id: UUID
    runtime_provider_version: str | None
    images: list[StaticImageResult]
    total_statistics: StaticStatistics
    class_statistics: dict[UUID, StaticStatistics]


class StaticPairedDifference(Contract):
    observation_count: int
    frozen_group_count: int
    independent_group_count: int | None
    ungrouped_observation_count: int
    absolute_error_change: float | None
    absolute_error_change_ci95: Limit | None


class StaticSnapshot(Contract):
    method: Literal["reefvision-reviewed-static-count-v1"] = "reefvision-reviewed-static-count-v1"
    software_version: str
    evidence: StaticEvidence
    evaluation_status: LineageStatus
    results: list[StaticModelResult]
    total_model_difference: StaticPairedDifference | None
    class_model_differences: dict[UUID, StaticPairedDifference]
    limitations: list[str]


class StaticComparisonRecord(Contract):
    id: UUID
    project_id: UUID
    content_sha256: Digest
    snapshot: StaticSnapshot
    source_id_map: dict[str, str] = Field(default_factory=dict)
    local_reference_sha256: Digest
    stale: bool = False


class StaticSummary(Contract):
    id: UUID
    status: str
    created_at: datetime
    reference_name: str
    model_names: list[str]
    evaluation_status: LineageStatus | None = None
