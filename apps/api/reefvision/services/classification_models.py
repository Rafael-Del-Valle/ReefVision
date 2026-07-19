"""Classification-aware model registration."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from reefvision.db.models import (
    ClassificationPrediction,
    ModelRegistration,
    TrainingRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.classification import (
    CLASSIFICATION_TASK,
    CLASSIFIER_PURPOSE,
    ULTRALYTICS_PROVIDER_ID,
    UltralyticsClassificationRegistrationProvider,
)
from reefvision.ml.providers import AnnotationAssistProvider, DetectionProvider
from reefvision.schemas.models import ModelRegistrationResponse, RegisterModelFromRunRequest
from reefvision.services.semantic_models import SemanticModelService
from reefvision.storage.projects import resolve_managed_project_path


class ClassificationModelService(SemanticModelService):
    """Register trusted Ultralytics classifiers without mixing model purposes."""

    def _provider_for_purpose(
        self,
        purpose: str,
    ) -> DetectionProvider | AnnotationAssistProvider:
        if purpose == CLASSIFIER_PURPOSE:
            return UltralyticsClassificationRegistrationProvider()
        return super()._provider_for_purpose(purpose)

    def _provider_for_registration(
        self,
        purpose: str,
        provider_name: str,
    ) -> DetectionProvider | AnnotationAssistProvider:
        if purpose == CLASSIFIER_PURPOSE:
            if provider_name.strip().casefold() != ULTRALYTICS_PROVIDER_ID:
                raise ValidationError(f"Unsupported classification provider: {provider_name}")
            return UltralyticsClassificationRegistrationProvider()
        return super()._provider_for_registration(purpose, provider_name)

    def register_model_from_run(
        self,
        project_id: str,
        payload: RegisterModelFromRunRequest,
    ) -> ModelRegistrationResponse:
        run = self.session.get(TrainingRun, payload.training_run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        if run.task != CLASSIFICATION_TASK:
            return super().register_model_from_run(project_id, payload)
        if run.project_id != project_id:
            raise ValidationError("Training runs must belong to the selected project")
        if run.status != "completed" or not run.result_checkpoint_path:
            raise ValidationError(
                "Only completed classification runs with a finalized checkpoint can be registered"
            )
        source_path = resolve_managed_project_path(
            self.settings,
            run.result_checkpoint_path,
        )
        artifact = dict(run.artifact_manifest_json)
        mode = str(artifact.get("classification_mode", "multiclass"))
        manifest_relative = str(artifact.get("dataset_manifest_path") or "")
        if not manifest_relative:
            raise ValidationError("Classification run is missing its dataset manifest")
        manifest_path = resolve_managed_project_path(self.settings, manifest_relative)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("Classification dataset manifest is unavailable") from exc
        raw_class_map = manifest.get("class_map", {})
        if not isinstance(raw_class_map, dict) or not raw_class_map:
            raise ValidationError("Classification dataset class mapping is missing")

        response = self._register_model_path(
            project_id,
            purpose=CLASSIFIER_PURPOSE,
            provider_name=ULTRALYTICS_PROVIDER_ID,
            source_path=source_path,
            source_filename=Path(run.result_checkpoint_path).name,
            display_name=payload.display_name or f"{run.run_name} classifier",
            notes=payload.notes or run.notes,
            metadata_overrides={
                "registered_from": "training_run",
                "source_training_run_id": run.id,
                "source_dataset_version_id": run.dataset_version_id,
                "source_dataset_manifest_sha256": run.dataset_manifest_sha256,
                "source_split_manifest_sha256": run.split_manifest_sha256,
                "source_metrics": dict(run.metrics_json),
                "classification_mode": mode,
                "classification_scope": "annotation_crop",
                "minimum_crop_size_px": int(artifact.get("minimum_crop_size_px", 10)),
                "padding_fraction": float(artifact.get("padding_fraction", 0.0)),
            },
        )
        model = self.session.get(ModelRegistration, response.id)
        if model is None:
            raise NotFoundError("Registered classifier could not be reloaded")
        labels = sorted(str(key) for key in raw_class_map)
        mapping = {
            str(key): str(value["label_class_id"])
            for key, value in raw_class_map.items()
            if isinstance(value, dict) and value.get("label_class_id")
        }
        model.class_map_json = {
            "labels": labels,
            "mapping": mapping,
            "classification_mode": mode,
            "state_labels": [label for label in labels if label in {"open", "closed"}],
            "dataset_class_map": raw_class_map,
        }
        self.session.commit()
        self.session.refresh(model)
        return ModelRegistrationResponse.model_validate(model)

    def delete_model(self, model_id: str) -> None:
        prediction_count = int(
            self.session.scalar(
                select(func.count(ClassificationPrediction.id)).where(
                    ClassificationPrediction.model_id == model_id
                )
            )
            or 0
        )
        if prediction_count:
            raise ConflictError("Classifiers with classification predictions cannot be removed")
        super().delete_model(model_id)
