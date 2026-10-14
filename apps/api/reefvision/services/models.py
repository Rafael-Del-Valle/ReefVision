"""Model registration and inference-job services."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ExperimentRecord,
    Job,
    LabelClass,
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.domain.enums import MODEL_PURPOSES
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.depth_anything_v2_provider import (
    DepthModelMetadata,
    DepthRegistrationProvider,
    TransformersDepthAnythingV2Provider,
)
from reefvision.ml.provider_hub import provider_for_registration
from reefvision.ml.providers import (
    AnnotationAssistProvider,
    AssistModelMetadata,
    DetectionModelMetadata,
    DetectionProvider,
)
from reefvision.ml.sam2_provider import TransformersSam2AssistProvider
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.predictions import PredictionRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.models import (
    InferenceJobCreateRequest,
    ModelRegistrationResponse,
    RegisterModelFromRunRequest,
)
from reefvision.storage.models import (
    copy_model_file,
    ensure_supported_model_extension,
    hash_model_file,
    project_model_directories,
    safe_model_name,
    stage_model_upload,
)
from reefvision.storage.projects import resolve_managed_project_path

RegistrationProvider = DetectionProvider | AnnotationAssistProvider | DepthRegistrationProvider
RegistrationMetadata = DetectionModelMetadata | AssistModelMetadata | DepthModelMetadata


def _humanize_catalog_family(catalog_model_id: str | None) -> str | None:
    if not catalog_model_id:
        return None
    segments = [segment.strip() for segment in catalog_model_id.split("/") if segment.strip()]
    if len(segments) < 2:
        return None
    token = segments[1]
    lowered = token.casefold()
    if lowered.startswith("yolov"):
        return f"YOLOv{token[5:]}"
    if lowered.startswith("yolo"):
        return f"YOLO{token[4:]}"
    return token.replace("_", " ").replace("-", " ")


class ModelService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.models = ModelRepository(session)
        self.images = ImageRepository(session)
        self.predictions = PredictionRepository(session)
        self.annotations = AnnotationRepository(session)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _model(self, model_id: str) -> ModelRegistration:
        model = self.models.get(model_id)
        if model is None:
            raise NotFoundError("Model not found")
        return model

    def _provider_for_purpose(self, purpose: str) -> RegistrationProvider:
        if purpose not in MODEL_PURPOSES:
            raise ValidationError("Unknown model purpose")
        if purpose == "depth":
            return TransformersDepthAnythingV2Provider()
        return provider_for_registration(purpose, settings=self.settings)

    def _provider_for_registration(self, purpose: str, provider_name: str) -> RegistrationProvider:
        normalized = provider_name.strip().casefold()
        if purpose == "assist" and normalized == "sam2":
            return TransformersSam2AssistProvider()
        if purpose == "depth":
            if normalized != "depth_anything_v2":
                raise ValidationError(f"Unsupported depth provider: {provider_name}")
            return TransformersDepthAnythingV2Provider()
        return provider_for_registration(
            purpose,
            provider_name=provider_name,
            settings=self.settings,
        )

    def _auto_class_map(
        self,
        *,
        project: Project,
        metadata: RegistrationMetadata,
    ) -> dict[str, object]:
        """Create an explicit project-class mapping for trusted detector labels.

        No prediction is accepted here. Creating a class only prepares a stable
        project identity for future human-reviewed or bulk-accepted proposals.
        All records are committed atomically with the model registration.
        """
        if not isinstance(metadata, DetectionModelMetadata):
            return {}

        project_classes = list(project.label_classes)
        by_name = {item.name.strip().casefold(): item for item in project_classes}
        next_index = max((item.class_index for item in project_classes), default=-1) + 1
        next_order = max((item.display_order for item in project_classes), default=-1) + 1
        colors = ("#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#06B6D4")
        mapping: dict[str, str | None] = {}
        labels: list[str] = []
        for raw_label in metadata.class_labels:
            label = str(raw_label).strip()
            if not label or len(label) > 200:
                raise ValidationError("Model class labels must have 1-200 characters")
            labels.append(label)
            key = label.casefold()
            label_class = by_name.get(key)
            if label_class is None:
                label_class = LabelClass(
                    id=str(uuid4()),
                    project_id=project.id,
                    class_index=next_index,
                    display_order=next_order,
                    name=label,
                    description=(
                        "Created from registered model class metadata; "
                        "predictions still require explicit acceptance."
                    ),
                    display_color=colors[next_index % len(colors)],
                    is_active=True,
                )
                self.session.add(label_class)
                by_name[key] = label_class
                next_index += 1
                next_order += 1
            # Archived classes are never reactivated silently.
            mapping[label] = label_class.id if label_class.is_active else None
        return {"labels": labels, "mapping": mapping}

    def list_models(
        self, project_id: str, *, purpose: str | None = None
    ) -> list[ModelRegistrationResponse]:
        self._project(project_id)
        return [
            ModelRegistrationResponse.model_validate(model)
            for model in self.models.list_for_project(project_id, purpose=purpose)
        ]

    def get_model(self, model_id: str) -> ModelRegistrationResponse:
        return ModelRegistrationResponse.model_validate(self._model(model_id))

    def _register_model_path(
        self,
        project_id: str,
        *,
        purpose: str,
        provider_name: str | None,
        source_path: Path,
        source_filename: str | None,
        display_name: str | None,
        notes: str | None,
        metadata_overrides: dict[str, object] | None = None,
    ) -> ModelRegistrationResponse:
        if purpose not in MODEL_PURPOSES:
            raise ValidationError("Unknown model purpose")
        project = self._project(project_id)
        filename = safe_model_name(source_filename)
        ensure_supported_model_extension(filename)
        if not source_path.is_file():
            raise NotFoundError("The requested model checkpoint is missing")
        sha256, size = hash_model_file(source_path)
        existing = self.models.find_by_checksum(project_id, sha256)
        if existing is not None:
            return ModelRegistrationResponse.model_validate(existing)

        resolved_name = (display_name or Path(filename).stem).strip() or Path(filename).stem
        conflicting_name = self.models.find_by_display_name(project_id, resolved_name)
        if conflicting_name is not None:
            raise ConflictError(
                "A different model is already registered with that display name in this project"
            )

        provider = (
            self._provider_for_registration(purpose, provider_name)
            if provider_name
            else self._provider_for_purpose(purpose)
        )
        metadata = provider.inspect_model(source_path)
        model_id = str(uuid4())
        suffix = Path(filename).suffix.lower()
        relative_managed = f"{project.storage_root}/models/{model_id}{suffix}"
        managed_destination = resolve_managed_project_path(self.settings, relative_managed)
        try:
            copied_sha256, copied_size = copy_model_file(source_path, managed_destination)
            if copied_sha256 != sha256 or copied_size != size:
                raise ValidationError("Managed model copy verification failed")
            model = ModelRegistration(
                id=model_id,
                project_id=project_id,
                purpose=purpose,
                display_name=resolved_name,
                source_filename=filename,
                managed_path=relative_managed,
                sha256=sha256,
                file_size_bytes=size,
                framework=metadata.framework,
                task=metadata.task,
                provider_name=metadata.provider_name,
                provider_version=metadata.provider_version,
                class_map_json=self._auto_class_map(project=project, metadata=metadata),
                input_size_json=(
                    metadata.input_size if isinstance(metadata, DetectionModelMetadata) else None
                ),
                metadata_json={
                    **metadata.metadata,
                    **(metadata_overrides or {}),
                },
                notes=notes.strip() if notes else None,
            )
            self.models.add(model)
            self.session.commit()
            self.session.refresh(model)
            return ModelRegistrationResponse.model_validate(model)
        except Exception:
            self.session.rollback()
            managed_destination.unlink(missing_ok=True)
            raise

    def register_model_upload(
        self,
        project_id: str,
        *,
        purpose: str,
        provider_name: str | None,
        upload_filename: str | None,
        upload_stream: BinaryIO,
        display_name: str | None,
        notes: str | None,
    ) -> ModelRegistrationResponse:
        filename = safe_model_name(upload_filename)
        suffix = Path(filename).suffix.lower()
        if suffix in {".pt", ".pth"} and not self.settings.allow_unsafe_pickled_models:
            raise ValidationError("Trusted PyTorch-style checkpoints are disabled by configuration")
        project = self._project(project_id)
        directories = project_model_directories(self.settings, project.storage_root)
        staging_path = directories["staging"] / f"{uuid4()}{suffix}"
        try:
            stage_model_upload(upload_stream, staging_path, self.settings.model_max_upload_bytes)
            response = self._register_model_path(
                project_id,
                purpose=purpose,
                provider_name=provider_name,
                source_path=staging_path,
                source_filename=filename,
                display_name=display_name,
                notes=notes,
            )
            staging_path.unlink(missing_ok=True)
            return response
        except Exception:
            self.session.rollback()
            staging_path.unlink(missing_ok=True)
            raise

    def register_model_from_run(
        self,
        project_id: str,
        payload: RegisterModelFromRunRequest,
    ) -> ModelRegistrationResponse:
        run = self.session.get(TrainingRun, payload.training_run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        if run.project_id != project_id:
            raise ValidationError("Training runs must belong to the selected project")
        if run.status != "completed" or not run.result_checkpoint_path:
            raise ValidationError(
                "Only completed training runs with a finalized checkpoint can be registered"
            )
        if run.task != "detect":
            raise ValidationError(
                "The current model registry integration supports detector checkpoints only"
            )
        source_path = resolve_managed_project_path(self.settings, run.result_checkpoint_path)
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
            "source_parameter_registry_version": run.parameter_registry_version,
            "source_selected_preset": run.selected_preset,
            "source_installation_state": run.installation_state,
            "source_architecture": run.architecture,
            "source_architecture_family": _humanize_catalog_family(run.catalog_model_id),
            "source_result_checkpoint_path": run.result_checkpoint_path,
            "source_metrics": dict(run.metrics_json),
        }
        if experiment is not None:
            metadata_overrides["source_experiment_id"] = experiment.id
        display_name = payload.display_name or f"{run.run_name} best"
        notes = payload.notes or run.notes
        return self._register_model_path(
            project_id,
            purpose="detector",
            provider_name=run.provider_id,
            source_path=source_path,
            source_filename=Path(run.result_checkpoint_path).name,
            display_name=display_name,
            notes=notes,
            metadata_overrides=metadata_overrides,
        )

    def delete_model(self, model_id: str) -> None:
        model = self._model(model_id)
        if self.predictions.has_any_for_model(model.id) or self.annotations.count_for_model(
            model.id
        ):
            raise ConflictError("Models with predictions or accepted annotations cannot be removed")
        path = resolve_managed_project_path(self.settings, model.managed_path)
        extracted_bundle = path.parent / f".{path.stem}.bundle"
        self.session.delete(model)
        self.session.commit()
        path.unlink(missing_ok=True)
        if path.suffix.casefold() == ".zip":
            shutil.rmtree(extracted_bundle, ignore_errors=True)

    def create_inference_job(
        self, project_id: str, payload: InferenceJobCreateRequest
    ) -> JobResponse:
        project = self._project(project_id)
        model = self._model(payload.model_id)
        if model.project_id != project.id or model.purpose != "detector":
            raise ValidationError("Inference jobs require a detector model from the same project")
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
                "image_ids": [image.id for image in images],
                "device": payload.device,
                "confidence_threshold": payload.confidence_threshold
                if payload.confidence_threshold is not None
                else self.settings.inference_default_confidence,
                "iou_threshold": payload.iou_threshold
                if payload.iou_threshold is not None
                else self.settings.inference_default_iou,
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)
