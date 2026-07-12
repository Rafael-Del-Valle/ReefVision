"""Fast bootstrap services for performance-sensitive workspaces."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.ml.dependencies import cached_lightweight_provider_preflight
from reefvision.ml.provider_hub import (
    cached_model_provider_catalog,
    cached_runtime_provider_statuses,
)
from reefvision.ml.ultralytics_registry import (
    cached_ultralytics_training_registry_summary,
)
from reefvision.schemas.bootstrap import (
    ModelHubBootstrapResponse,
    TrainingWorkspaceBootstrapResponse,
    UltralyticsTrainingRegistrySummarySnapshotResponse,
)
from reefvision.schemas.models import (
    ModelProviderResponse,
    ProviderDependencyPackageResponse,
    ProviderDependencyPreflightResponse,
    ProviderDependencyStatusResponse,
    RuntimeProviderStatusResponse,
)
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.services.models import ModelService
from reefvision.services.training import TrainingService


class BootstrapService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.catalog = ModelCatalogService(session, settings)
        self.models = ModelService(session, settings)
        self.training = TrainingService(session, settings)

    def model_hub_bootstrap(self, project_id: str) -> ModelHubBootstrapResponse:
        catalog = self.catalog.list_project_catalog(project_id, workflow="model_hub")
        models = self.models.list_models(project_id)
        warnings = list(catalog.validation_warnings)
        providers: list[ModelProviderResponse] = []
        provider_preflight_response: ProviderDependencyPreflightResponse | None = None
        runtime_status_responses: list[RuntimeProviderStatusResponse] = []
        training_compatibility_response: (
            UltralyticsTrainingRegistrySummarySnapshotResponse | None
        ) = None
        provider_summary_states: dict[str, str] = {}
        provider_catalog_checked_at = None
        provider_preflight_checked_at = None
        runtime_statuses_checked_at = None
        training_compatibility_checked_at = None

        try:
            provider_catalog = cached_model_provider_catalog(self.settings)
            provider_catalog_checked_at = provider_catalog.checked_at
            providers = [
                ModelProviderResponse.model_validate(asdict(provider))
                for provider in provider_catalog.value
            ]
        except Exception as exc:
            warnings.append(f"Provider catalog refresh failed: {exc}")

        try:
            provider_preflight = cached_lightweight_provider_preflight(self.settings)
            provider_preflight_checked_at = provider_preflight.checked_at
            provider_preflight_response = ProviderDependencyPreflightResponse(
                providers=[
                    ProviderDependencyStatusResponse(
                        provider_name=report.provider_name,
                        display_name=report.display_name,
                        purpose=report.purpose,
                        provider_version=report.provider_version,
                        status=report.status,
                        ready=report.ready,
                        tested_python=report.tested_python,
                        current_python=report.current_python,
                        tested_platform=report.tested_platform,
                        current_platform=report.current_platform,
                        tested_cuda=report.tested_cuda,
                        current_cuda=report.current_cuda,
                        automatic_downloads_disabled=report.automatic_downloads_disabled,
                        explicit_checkpoint_required=report.explicit_checkpoint_required,
                        requirements_file=report.requirements_file,
                        issues=list(report.issues),
                        packages=[
                            ProviderDependencyPackageResponse(
                                distribution_name=item.distribution_name,
                                required_version=item.required_version,
                                installed_version=item.installed_version,
                                status=item.status,
                            )
                            for item in report.package_statuses
                        ],
                    )
                    for report in provider_preflight.value
                ]
            )
            provider_summary_states = {
                report.provider_name: report.status for report in provider_preflight.value
            }
        except Exception as exc:
            warnings.append(f"Provider preflight refresh failed: {exc}")

        try:
            runtime_statuses = cached_runtime_provider_statuses()
            runtime_statuses_checked_at = runtime_statuses.checked_at
            runtime_status_responses = [
                RuntimeProviderStatusResponse.model_validate(asdict(runtime))
                for runtime in runtime_statuses.value
            ]
        except Exception as exc:
            warnings.append(f"Runtime status refresh failed: {exc}")

        try:
            training_compatibility = cached_ultralytics_training_registry_summary(self.settings)
            training_compatibility_checked_at = training_compatibility.checked_at
            training_compatibility_response = (
                UltralyticsTrainingRegistrySummarySnapshotResponse.model_validate(
                    training_compatibility.value,
                    from_attributes=True,
                )
            )
        except Exception as exc:
            warnings.append(f"Training compatibility refresh failed: {exc}")
        return ModelHubBootstrapResponse(
            application_version=__version__,
            catalog=catalog,
            models=models,
            providers=providers,
            provider_preflight=provider_preflight_response,
            runtime_statuses=runtime_status_responses,
            training_compatibility=training_compatibility_response,
            provider_summary_states=provider_summary_states,
            validation_warnings=warnings,
            last_refresh_timestamp=datetime.now(UTC),
            provider_catalog_checked_at=provider_catalog_checked_at,
            provider_preflight_checked_at=provider_preflight_checked_at,
            runtime_statuses_checked_at=runtime_statuses_checked_at,
            training_compatibility_checked_at=training_compatibility_checked_at,
        )

    def training_workspace_bootstrap(
        self,
        project_id: str,
    ) -> TrainingWorkspaceBootstrapResponse:
        draft_summaries = self.training.list_draft_summaries(project_id)
        selected_draft = self.training.get_draft(draft_summaries[0].id) if draft_summaries else None
        return TrainingWorkspaceBootstrapResponse(
            draft_summaries=draft_summaries,
            selected_draft=selected_draft,
            providers=self.training.list_providers(),
            catalog=self.catalog.list_project_catalog(project_id, workflow="training"),
        )
