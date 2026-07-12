"""Training workspace API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TrainingCheckpointSource = Literal["scratch", "registered_model", "managed_catalog"]
TrainingPreflightStatus = Literal["ready", "ready_with_warnings", "blocked"]


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class TrainingDraftWriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    run_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    dataset_version_id: str | None = Field(default=None, max_length=36)
    task: str | None = Field(default=None, max_length=40)
    catalog_model_id: str | None = Field(default=None, max_length=255)
    provider_id: str | None = Field(default=None, max_length=100)
    architecture: str | None = Field(default=None, max_length=200)
    initial_checkpoint_source: TrainingCheckpointSource = "scratch"
    initial_checkpoint_model_id: str | None = Field(default=None, max_length=36)
    device: str = Field(default="auto", min_length=1, max_length=60)
    precision: str = Field(default="fp32", min_length=1, max_length=30)
    random_seed: int | None = None
    tiling_config: dict[str, Any] = Field(default_factory=dict)
    training_config: dict[str, Any] = Field(default_factory=dict)
    tuning_config: dict[str, Any] = Field(default_factory=dict)
    evaluation_config: dict[str, Any] = Field(default_factory=dict)
    resource_limits: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "name",
        "run_name",
        "notes",
        "task",
        "catalog_model_id",
        "provider_id",
        "architecture",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value


class TrainingDraftPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    run_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    dataset_version_id: str | None = Field(default=None, max_length=36)
    task: str | None = Field(default=None, max_length=40)
    catalog_model_id: str | None = Field(default=None, max_length=255)
    provider_id: str | None = Field(default=None, max_length=100)
    architecture: str | None = Field(default=None, max_length=200)
    initial_checkpoint_source: TrainingCheckpointSource | None = None
    initial_checkpoint_model_id: str | None = Field(default=None, max_length=36)
    device: str | None = Field(default=None, min_length=1, max_length=60)
    precision: str | None = Field(default=None, min_length=1, max_length=30)
    random_seed: int | None = None
    tiling_config: dict[str, Any] | None = None
    training_config: dict[str, Any] | None = None
    tuning_config: dict[str, Any] | None = None
    evaluation_config: dict[str, Any] | None = None
    resource_limits: dict[str, Any] | None = None

    @field_validator(
        "name",
        "run_name",
        "notes",
        "task",
        "catalog_model_id",
        "provider_id",
        "architecture",
        mode="before",
    )
    @classmethod
    def strip_patch_strings(cls, value: object) -> object:
        return _strip(value) if isinstance(value, str) or value is None else value


class TrainingProviderArchitectureResponse(BaseModel):
    architecture_id: str
    display_name: str
    task: str
    source: str


class TrainingProviderResponse(BaseModel):
    provider_id: str
    display_name: str
    provider_version: str
    supported_tasks: list[str]
    supported_precision_modes: list[str]
    supports_tiling: bool
    supports_tuning: bool
    supports_packaged_desktop: bool
    warning: str | None
    architectures: list[TrainingProviderArchitectureResponse]


class TrainingLeakageAuditResponse(BaseModel):
    blocked: bool
    warnings: list[str]
    blockers: list[str]
    image_leak_count: int
    group_leak_count: int


class TrainingDatasetSummaryResponse(BaseModel):
    dataset_version_id: str | None
    dataset_manifest_sha256: str | None
    split_manifest_sha256: str | None
    image_count: int
    annotation_count: int
    split_counts: dict[str, int]
    group_count: int
    warnings: list[str]


class TrainingPreflightResponse(BaseModel):
    status: TrainingPreflightStatus
    warnings: list[str]
    blockers: list[str]
    dataset: TrainingDatasetSummaryResponse
    leakage_audit: TrainingLeakageAuditResponse
    resource_snapshot: dict[str, Any]
    provider_dependency_status: dict[str, Any]


class TrainingDraftResponse(BaseModel):
    id: str
    project_id: str
    name: str
    run_name: str | None
    notes: str | None
    dataset_version_id: str | None
    dataset_manifest_sha256: str | None
    split_manifest_sha256: str | None
    task: str | None
    catalog_model_id: str | None
    provider_id: str | None
    architecture: str | None
    initial_checkpoint_source: str
    initial_checkpoint_model_id: str | None
    resolved_model_asset_id: str | None
    resolved_model_checksum: str | None
    parameter_registry_version: str | None
    selected_preset: str | None
    installation_state: str | None
    device: str
    precision: str
    random_seed: int | None
    tiling_config: dict[str, Any]
    training_config: dict[str, Any]
    tuning_config: dict[str, Any]
    evaluation_config: dict[str, Any]
    resource_limits: dict[str, Any]
    validation_state: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TrainingDraftSummaryResponse(BaseModel):
    id: str
    project_id: str
    name: str
    run_name: str | None
    dataset_version_id: str | None
    task: str | None
    catalog_model_id: str | None
    provider_id: str | None
    architecture: str | None
    initial_checkpoint_source: str
    validation_status: TrainingPreflightStatus | None
    warning_count: int
    blocker_count: int
    created_at: datetime
    updated_at: datetime


class TrainingRunCreateRequest(BaseModel):
    draft_id: str = Field(min_length=1, max_length=36)


class TrainingRunResponse(BaseModel):
    id: str
    project_id: str
    draft_id: str | None
    dataset_version_id: str | None
    dataset_manifest_sha256: str
    split_manifest_sha256: str
    task: str
    catalog_model_id: str | None
    provider_id: str
    architecture: str
    initial_checkpoint_source: str
    initial_checkpoint_model_id: str | None
    resolved_model_asset_id: str | None
    resolved_model_checksum: str | None
    parameter_registry_version: str | None
    selected_preset: str | None
    installation_state: str | None
    device: str
    precision: str
    run_name: str
    notes: str | None
    random_seed: int | None
    tiling_config: dict[str, Any]
    training_config: dict[str, Any]
    tuning_config: dict[str, Any]
    evaluation_config: dict[str, Any]
    resource_limits: dict[str, Any]
    preflight_report: dict[str, Any]
    draft_snapshot: dict[str, Any]
    status: str
    stage: str
    progress_epoch: int
    progress_total_epochs: int
    metrics: dict[str, Any]
    metrics_history: dict[str, Any]
    warnings: list[str]
    artifact_manifest: dict[str, Any]
    logs_path: str | None
    result_checkpoint_path: str | None
    job_id: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class TrainingTilingRequest(BaseModel):
    dataset_version_id: str = Field(min_length=1, max_length=36)
    tiling_config: dict[str, Any] = Field(default_factory=dict)


class TrainingTilingPreviewTileResponse(BaseModel):
    image_id: str
    split: str
    x: int
    y: int
    width: int
    height: int
    retained_annotation_count: int


class TrainingTilingEstimateResponse(BaseModel):
    blocked: bool
    warnings: list[str]
    tile_count: int
    positive_tile_count: int
    background_tile_count: int
    estimated_storage_bytes: int
    preview_tiles: list[TrainingTilingPreviewTileResponse]


class ExperimentRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    training_run_id: str
    dataset_version_id: str | None
    dataset_manifest_sha256: str
    split_manifest_sha256: str
    task: str
    provider_id: str
    architecture: str
    summary_metrics_json: dict[str, Any]
    comparison_warnings_json: list[str]
    artifact_manifest_json: dict[str, Any]
    package_versions_json: dict[str, Any]
    created_at: datetime


class ExperimentCompareRequest(BaseModel):
    experiment_ids: list[str] = Field(min_length=2)


class ExperimentCompareResponse(BaseModel):
    experiments: list[ExperimentRecordResponse]
    warnings: list[str]
