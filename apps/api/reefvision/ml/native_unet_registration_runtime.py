"""Register native ReefVision U-Net training results as semantic segmenters."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from reefvision.db.models import ExperimentRecord, ModelRegistration, TrainingRun
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.reefvision_unet import inspect_unet_checkpoint
from reefvision.ml.reefvision_unet_semantic import REEFVISION_UNET_PROVIDER_ID
from reefvision.ml.semantic_segmentation import SEMANTIC_SEGMENTATION_TASK
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.storage.models import copy_model_file, hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

_APPLIED = False


def apply_native_unet_registration_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return

    from reefvision.services.semantic_models import SemanticModelService

    original = SemanticModelService.register_model_from_run

    def register_model_from_run(
        self: Any,
        project_id: str,
        payload: Any,
    ) -> ModelRegistrationResponse:
        run = self.session.get(TrainingRun, payload.training_run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        if (
            run.task != SEMANTIC_SEGMENTATION_TASK
            or run.provider_id != REEFVISION_UNET_PROVIDER_ID
        ):
            return original(self, project_id, payload)
        if run.project_id != project_id:
            raise ValidationError("Training runs must belong to the selected project")
        if run.status != "completed" or not run.result_checkpoint_path:
            raise ValidationError(
                "Only completed native U-Net runs with a finalized checkpoint can be registered"
            )

        project = self._project(project_id)
        source_path = resolve_managed_project_path(self.settings, run.result_checkpoint_path)
        metadata = inspect_unet_checkpoint(source_path)
        checksum, size = hash_model_file(source_path)
        existing = self.models.find_by_checksum(project_id, checksum)
        if existing is not None:
            return ModelRegistrationResponse.model_validate(existing)

        display_name = (payload.display_name or f"{run.run_name} semantic").strip()
        if self.models.find_by_display_name(project_id, display_name) is not None:
            raise ConflictError(
                "A different model is already registered with that display name in this project"
            )

        labels_by_name = {
            label_class.name.strip().casefold(): label_class.id
            for label_class in project.label_classes
            if label_class.is_active
        }
        foreground_labels = list(metadata.class_labels[1:])
        classes = [
            {
                "class_index": index,
                "pixel_value": index,
                "class_name": label,
            }
            for index, label in enumerate(foreground_labels, start=1)
        ]
        class_map = {
            "labels": foreground_labels,
            "mapping": {
                label: labels_by_name.get(label.strip().casefold())
                for label in foreground_labels
            },
            "pixel_values": {
                label: index
                for index, label in enumerate(foreground_labels, start=1)
            },
        }

        model_id = str(uuid4())
        suffix = (
            source_path.suffix.casefold()
            if source_path.suffix.casefold() in {".pt", ".pth"}
            else ".pt"
        )
        managed_path = f"{project.storage_root}/models/{model_id}{suffix}"
        destination = resolve_managed_project_path(self.settings, managed_path)
        copied_checksum, copied_size = copy_model_file(source_path, destination)
        if copied_checksum != checksum or copied_size != size:
            destination.unlink(missing_ok=True)
            raise ValidationError("Managed native U-Net copy verification failed")

        experiment = self.session.scalar(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
        )
        model = ModelRegistration(
            id=model_id,
            project_id=project_id,
            purpose="semantic_segmenter",
            display_name=display_name,
            source_filename=source_path.name,
            managed_path=managed_path,
            sha256=checksum,
            file_size_bytes=size,
            framework="pytorch",
            task=SEMANTIC_SEGMENTATION_TASK,
            provider_name=REEFVISION_UNET_PROVIDER_ID,
            provider_version="1.0",
            class_map_json=class_map,
            input_size_json={"width": metadata.image_size, "height": metadata.image_size},
            metadata_json={
                "format": "reefvision_unet_v1",
                "provider_id": REEFVISION_UNET_PROVIDER_ID,
                "provider_version": "1.0",
                "preset": metadata.preset,
                "image_size": metadata.image_size,
                "classes": classes,
                "registered_from": "training_run",
                "source_training_run_id": run.id,
                "source_dataset_version_id": run.dataset_version_id,
                "source_dataset_manifest_sha256": run.dataset_manifest_sha256,
                "source_split_manifest_sha256": run.split_manifest_sha256,
                "source_result_checkpoint_path": run.result_checkpoint_path,
                "source_metrics": dict(run.metrics_json),
                "source_experiment_id": experiment.id if experiment is not None else None,
                "proposal_geometry": "raster_mask",
            },
            notes=(payload.notes or run.notes),
        )
        try:
            self.models.add(model)
            self.session.commit()
            self.session.refresh(model)
            return ModelRegistrationResponse.model_validate(model)
        except Exception:
            self.session.rollback()
            destination.unlink(missing_ok=True)
            raise

    SemanticModelService.register_model_from_run = register_model_from_run
    _APPLIED = True
