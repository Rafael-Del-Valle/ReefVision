"""Segmentation-aware extensions for model registration and inference jobs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from reefvision.db.models import ExperimentRecord, Job, TrainingRun
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.providers import (
    DetectionModelMetadata,
    UltralyticsDetectionProvider,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.models import (
    InferenceJobCreateRequest,
    ModelRegistrationResponse,
    RegisterModelFromRunRequest,
)
from reefvision.services.models import ModelService, RegistrationProvider, _humanize_catalog_family
from reefvision.storage.projects import resolve_managed_project_path


class UltralyticsSegmentationRegistrationProvider(UltralyticsDetectionProvider):
    """Inspect Ultralytics checkpoints while enforcing the segment task."""

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        metadata = super().inspect_model(model_path)
        if metadata.task != "segment":
            raise ValidationError(
                "Segmenter registration requires an Ultralytics segmentation checkpoint"
            )
        return replace(
            metadata,
            metadata={
                **metadata.metadata,
                "proposal_geometry": "polygon_mask",
                "segmentation_masks_exposed_in_editor": True,
            },
        )


class SegmentationModelService(ModelService):
    """Register and execute distinct Ultralytics segmentation models."""

    def _provider_for_purpose(
        self,
        purpose: str,
    ) -> RegistrationProvider:
        if purpose == "segmenter":
            return UltralyticsSegmentationRegistrationProvider()
        return super()._provider_for_purpose(purpose)

    def _provider_for_registration(
        self,
        purpose: str,
        provider_name: str,
    ) -> RegistrationProvider:
        if purpose == "segmenter":
            if provider_name.strip().casefold() != "ultralytics":
                raise ValidationError(f"Unsupported segmentation provider: {provider_name}")
            return UltralyticsSegmentationRegistrationProvider()
        return super()._provider_for_registration(purpose, provider_name)

    def register_model_from_run(
        self,
        project_id: str,
        payload: RegisterModelFromRunRequest,
    ) -> ModelRegistrationResponse:
        run = self.session.get(TrainingRun, payload.training_run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        if run.task != "segment":
            return super().register_model_from_run(project_id, payload)
        if run.project_id != project_id:
            raise ValidationError("Training runs must belong to the selected project")
        if run.status != "completed" or not run.result_checkpoint_path:
            raise ValidationError(
                "Only completed training runs with a finalized checkpoint can be registered"
            )
        source_path = resolve_managed_project_path(
            self.settings,
            run.result_checkpoint_path,
        )
        experiment = self.session.scalar(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
        )
        metadata_overrides: dict[str, object] = {
            "registered_from": "training_run",
            "source_training_run_id": run.id,
            "source_dataset_version_id": run.dataset_version_id,
            "source_dataset_manifest_sha256": run.dataset_manifest_sha256,
            "source_split_manifest_sha256": run.split_manifest_sha256,
            "source_catalog_model_id": run.catalog_model_id,
            "source_resolved_model_asset_id": run.resolved_model_asset_id,
            "source_resolved_model_checksum": run.resolved_model_checksum,
            "source_parameter_registry_version": (run.parameter_registry_version),
            "source_selected_preset": run.selected_preset,
            "source_installation_state": run.installation_state,
            "source_architecture": run.architecture,
            "source_architecture_family": _humanize_catalog_family(run.catalog_model_id),
            "source_result_checkpoint_path": run.result_checkpoint_path,
            "source_metrics": dict(run.metrics_json),
            "proposal_geometry": "polygon_mask",
            "segmentation_masks_exposed_in_editor": True,
        }
        if experiment is not None:
            metadata_overrides["source_experiment_id"] = experiment.id
        display_name = payload.display_name or f"{run.run_name} best"
        notes = payload.notes or run.notes
        return self._register_model_path(
            project_id,
            purpose="segmenter",
            provider_name=run.provider_id,
            source_path=source_path,
            source_filename=Path(run.result_checkpoint_path).name,
            display_name=display_name,
            notes=notes,
            metadata_overrides=metadata_overrides,
        )

    def create_inference_job(
        self,
        project_id: str,
        payload: InferenceJobCreateRequest,
    ) -> JobResponse:
        project = self._project(project_id)
        model = self._model(payload.model_id)
        valid_model = model.project_id == project.id and (
            (model.purpose == "detector" and model.task == "detect")
            or (model.purpose == "segmenter" and model.task == "segment")
        )
        if not valid_model:
            raise ValidationError(
                "Inference jobs require a compatible detector or segmenter model "
                "from the same project"
            )
        images = self.images.list_by_ids(payload.image_ids)
        if len(images) != len(payload.image_ids):
            raise ValidationError("One or more requested images do not exist")
        if any(image.project_id != project_id for image in images):
            raise ValidationError("Inference images must belong to the same project as the model")
        job = Job(
            project_id=project_id,
            job_type="inference",
            status="queued",
            progress_total=len(images),
            request_json={
                "model_id": model.id,
                "model_task": model.task,
                "image_ids": [image.id for image in images],
                "device": payload.device,
                "confidence_threshold": (
                    payload.confidence_threshold
                    if payload.confidence_threshold is not None
                    else self.settings.inference_default_confidence
                ),
                "iou_threshold": (
                    payload.iou_threshold
                    if payload.iou_threshold is not None
                    else self.settings.inference_default_iou
                ),
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)
