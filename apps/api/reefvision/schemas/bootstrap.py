"""Bootstrap response schemas for fast Model Hub and Training rendering."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from reefvision.schemas.model_catalog import ModelCatalogResponse
from reefvision.schemas.models import (
    ModelProviderResponse,
    ModelRegistrationResponse,
    ProviderDependencyPreflightResponse,
    RuntimeProviderStatusResponse,
    UltralyticsTrainingRegistrySummaryResponse,
)
from reefvision.schemas.training import (
    TrainingDraftResponse,
    TrainingDraftSummaryResponse,
    TrainingProviderResponse,
)


class UltralyticsTrainingRegistrySummarySnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_name: str
    provider_version: str
    ultralytics_version: str | None
    pinned_version_matches_installed: bool
    supported_tasks: list[str]
    supported_modes: list[str]
    summary: UltralyticsTrainingRegistrySummaryResponse


class ModelHubBootstrapResponse(BaseModel):
    application_version: str
    catalog: ModelCatalogResponse
    models: list[ModelRegistrationResponse] = Field(default_factory=list)
    providers: list[ModelProviderResponse] = Field(default_factory=list)
    provider_preflight: ProviderDependencyPreflightResponse | None = None
    runtime_statuses: list[RuntimeProviderStatusResponse] = Field(default_factory=list)
    training_compatibility: UltralyticsTrainingRegistrySummarySnapshotResponse | None = None
    provider_summary_states: dict[str, str] = Field(default_factory=dict)
    validation_warnings: list[str] = Field(default_factory=list)
    last_refresh_timestamp: datetime
    provider_catalog_checked_at: datetime | None = None
    provider_preflight_checked_at: datetime | None = None
    runtime_statuses_checked_at: datetime | None = None
    training_compatibility_checked_at: datetime | None = None


class TrainingWorkspaceBootstrapResponse(BaseModel):
    draft_summaries: list[TrainingDraftSummaryResponse]
    selected_draft: TrainingDraftResponse | None = None
    providers: list[TrainingProviderResponse]
    catalog: ModelCatalogResponse
