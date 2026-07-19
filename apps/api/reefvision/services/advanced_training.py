"""Training service extensions for tuning, validation, and RGB-D safeguards."""

from __future__ import annotations

from reefvision.domain.errors import ValidationError
from reefvision.ml.ultralytics_tuning import normalize_tuning_config
from reefvision.schemas.depth import DepthTrainingConfiguration
from reefvision.schemas.training import (
    TrainingDraftWriteRequest,
    TrainingPreflightResponse,
    TrainingProviderResponse,
)
from reefvision.services.semantic_training import SemanticTrainingService


class AdvancedTrainingService(SemanticTrainingService):
    """Expose Ultralytics tuning and reject unsupported implicit RGB-D training."""

    def list_providers(self) -> list[TrainingProviderResponse]:
        providers = super().list_providers()
        for provider in providers:
            if provider.provider_id == "ultralytics":
                provider.supports_tuning = True
                provider.warning = (
                    "Detection and polygon instance-segmentation support training, "
                    "Ultralytics hyperparameter tuning, explicit class-wise validation, "
                    "and configurable ReefVision reports. Standard checkpoints consume RGB "
                    "only; depth inputs require a separate RGB-D provider and retraining."
                )
        return providers

    def preflight(
        self,
        project_id: str,
        payload: TrainingDraftWriteRequest,
    ) -> TrainingPreflightResponse:
        response = super().preflight(project_id, payload)
        resolved_task = payload.task
        if resolved_task not in {"detect", "segment"}:
            return response

        response.blockers = [
            blocker
            for blocker in response.blockers
            if "tuning" not in blocker.casefold()
            or "not implemented" not in blocker.casefold()
        ]
        try:
            tuning = normalize_tuning_config(payload.tuning_config)
        except ValidationError as exc:
            response.blockers.append(str(exc))
        else:
            if tuning["mode"] == "ultralytics":
                total_epochs = int(tuning["iterations"]) * int(
                    tuning["epochs_per_trial"]
                )
                response.warnings.append(
                    f"Tuning will run {tuning['iterations']} trials of "
                    f"{tuning['epochs_per_trial']} epochs before final training "
                    f"({total_epochs} tuning epochs total)."
                )
                if not tuning.get("search_space"):
                    response.warnings.append(
                        "No custom search space was supplied; Ultralytics defaults will be used."
                    )

        training_config = dict(payload.training_config or {})
        raw_depth = training_config.get("depth_input", {"input_mode": "none"})
        try:
            depth_config = DepthTrainingConfiguration.model_validate(raw_depth)
        except ValueError as exc:
            response.blockers.append(f"Invalid depth-input configuration: {exc}")
        else:
            if depth_config.input_mode != "none":
                if payload.provider_id == "ultralytics" or payload.provider_id is None:
                    response.blockers.append(
                        "Standard Ultralytics detection and segmentation checkpoints accept "
                        "three-channel RGB input. Select a dedicated ReefVision RGB-D provider "
                        "before enabling fourth-channel or fusion-based depth input."
                    )
                response.warnings.append(
                    "RGB-D training changes the model input contract and requires training or "
                    "fine-tuning with aligned depth maps; depth cannot be added only at inference."
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
