"""Training service extensions for Ultralytics tuning and final validation."""

from __future__ import annotations

from reefvision.domain.errors import ValidationError
from reefvision.ml.ultralytics_tuning import normalize_tuning_config
from reefvision.schemas.training import (
    TrainingDraftWriteRequest,
    TrainingPreflightResponse,
    TrainingProviderResponse,
)
from reefvision.services.semantic_training import SemanticTrainingService


class AdvancedTrainingService(SemanticTrainingService):
    """Expose tuning for Ultralytics detection and segmentation workflows."""

    def list_providers(self) -> list[TrainingProviderResponse]:
        providers = super().list_providers()
        for provider in providers:
            if provider.provider_id == "ultralytics":
                provider.supports_tuning = True
                provider.warning = (
                    "Detection and polygon instance-segmentation support training, "
                    "Ultralytics hyperparameter tuning, explicit class-wise validation, "
                    "and configurable ReefVision reports. Raster masks use nnU-Net."
                )
        return providers

    def preflight(
        self,
        project_id: str,
        payload: TrainingDraftWriteRequest,
    ) -> TrainingPreflightResponse:
        response = super().preflight(project_id, payload)
        if payload.task not in {"detect", "segment"}:
            return response

        response.blockers = [
            blocker
            for blocker in response.blockers
            if "tuning" not in blocker.casefold() or "not implemented" not in blocker.casefold()
        ]
        try:
            config = normalize_tuning_config(payload.tuning_config)
        except ValidationError as exc:
            response.blockers.append(str(exc))
        else:
            if config["mode"] == "ultralytics":
                total_epochs = int(config["iterations"]) * int(config["epochs_per_trial"])
                response.warnings.append(
                    f"Tuning will run {config['iterations']} trials of "
                    f"{config['epochs_per_trial']} epochs before final training "
                    f"({total_epochs} tuning epochs total)."
                )
                if not config.get("search_space"):
                    response.warnings.append(
                        "No custom search space was supplied; Ultralytics defaults will be used."
                    )
        response.blockers = self._dedupe_messages(response.blockers)
        response.warnings = self._dedupe_messages(response.warnings)
        response.status = (
            "blocked"
            if response.blockers
            else "ready_with_warnings"
            if response.warnings
            else "ready"
        )
        return response
