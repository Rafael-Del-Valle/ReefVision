"""Semantic model registration and inference-job integration."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from reefvision.db.models import (
    ExperimentRecord,
    Job,
    ModelRegistration,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseModelSchemaBinding,
    TrainingRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.semantic_segmentation import (
    NNUNET_PROVIDER_ID,
    SEMANTIC_SEGMENTATION_TASK,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.models import (
    InferenceJobCreateRequest,
    ModelRegistrationResponse,
    PoseLandmarkSchemaUpdateRequest,
    RegisterModelFromRunRequest,
)
from reefvision.services.segmentation_models import SegmentationModelService
from reefvision.storage.models import copy_model_file, hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

SEMANTIC_MODEL_PURPOSE = "semantic_segmenter"
SEMANTIC_BUNDLE_METADATA = "reefvision-semantic-model.json"


class SemanticModelService(SegmentationModelService):
    """Register nnU-Net bundles and queue semantic inference jobs."""

    def _semantic_metadata(self, source_path: Path) -> dict[str, Any]:
        if not source_path.is_file() or source_path.suffix.casefold() != ".zip":
            raise ValidationError("Semantic model registration requires a ReefVision .zip bundle")
        try:
            with zipfile.ZipFile(source_path) as archive:
                raw_payload = json.loads(archive.read(SEMANTIC_BUNDLE_METADATA).decode("utf-8"))
        except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise ValidationError("Semantic model bundle metadata is invalid") from exc
        if not isinstance(raw_payload, dict):
            raise ValidationError("Semantic model bundle metadata must be an object")
        payload: dict[str, Any] = raw_payload
        if payload.get("format") != "reefvision_nnunet_v2":
            raise ValidationError("The selected ZIP is not a ReefVision nnU-Net model bundle")
        if payload.get("provider_id") != NNUNET_PROVIDER_ID:
            raise ValidationError("The semantic model bundle provider is unsupported")
        classes = payload.get("classes")
        if not isinstance(classes, list) or not classes:
            raise ValidationError("Semantic model bundle classes are missing")
        if any(
            not isinstance(item, dict) or "class_name" not in item or "pixel_value" not in item
            for item in classes
        ):
            raise ValidationError("Semantic model bundle class metadata is invalid")
        return payload

    def register_model_from_run(
        self,
        project_id: str,
        payload: RegisterModelFromRunRequest,
    ) -> ModelRegistrationResponse:
        run = self.session.get(TrainingRun, payload.training_run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        if run.task != SEMANTIC_SEGMENTATION_TASK:
            return super().register_model_from_run(project_id, payload)
        if run.project_id != project_id:
            raise ValidationError("Training runs must belong to the selected project")
        if run.status != "completed" or not run.result_checkpoint_path:
            raise ValidationError(
                "Only completed semantic runs with a finalized bundle can be registered"
            )

        project = self._project(project_id)
        source_path = resolve_managed_project_path(
            self.settings,
            run.result_checkpoint_path,
        )
        bundle = self._semantic_metadata(source_path)
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
        raw_classes = bundle["classes"]
        if not isinstance(raw_classes, list):
            raise ValidationError("Semantic model bundle classes are invalid")
        classes: list[dict[str, Any]] = [item for item in raw_classes if isinstance(item, dict)]
        labels = [str(item["class_name"]) for item in classes]
        class_map = {
            "labels": labels,
            "mapping": {label: labels_by_name.get(label.strip().casefold()) for label in labels},
            "pixel_values": {str(item["class_name"]): int(item["pixel_value"]) for item in classes},
        }

        model_id = str(uuid4())
        managed_path = f"{project.storage_root}/models/{model_id}.zip"
        destination = resolve_managed_project_path(self.settings, managed_path)
        copied_checksum, copied_size = copy_model_file(source_path, destination)
        if copied_checksum != checksum or copied_size != size:
            destination.unlink(missing_ok=True)
            raise ValidationError("Managed semantic model copy verification failed")

        experiment = self.session.scalar(
            select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
        )
        model = ModelRegistration(
            id=model_id,
            project_id=project_id,
            purpose=SEMANTIC_MODEL_PURPOSE,
            display_name=display_name,
            source_filename=source_path.name,
            managed_path=managed_path,
            sha256=checksum,
            file_size_bytes=size,
            framework="nnunetv2",
            task=SEMANTIC_SEGMENTATION_TASK,
            provider_name=NNUNET_PROVIDER_ID,
            provider_version=str(bundle.get("provider_version", "unknown")),
            class_map_json=class_map,
            input_size_json=None,
            metadata_json={
                **bundle,
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

    def set_pose_landmark_schema(
        self,
        model_id: str,
        payload: PoseLandmarkSchemaUpdateRequest,
    ) -> ModelRegistrationResponse:
        model = self._model(model_id)
        if model.task != "pose":
            raise ValidationError("Landmark schemas can only be assigned to pose models")

        expanded_labels = payload.expanded_labels
        metadata = dict(model.metadata_json or {})
        raw_shape = metadata.get("pose_keypoint_shape")
        expected_count: int | None = None
        if isinstance(raw_shape, list) and raw_shape and isinstance(raw_shape[0], int):
            expected_count = int(raw_shape[0])

        if expected_count is not None and len(expanded_labels) != expected_count:
            raise ValidationError(
                "Pose landmark schema defines "
                f"{len(expanded_labels)} landmarks but the checkpoint expects "
                f"{expected_count}"
            )

        groups = [{"name": group.name, "count": group.count} for group in payload.groups]
        schema_payload = {
            "schema_version": "pose-landmarks-0001",
            "groups": groups,
            "expanded_labels": expanded_labels,
            "keypoint_count": len(expanded_labels),
            "allows_repeated_labels": any(group.count > 1 for group in payload.groups),
        }
        content_hash = hashlib.sha256(
            json.dumps(
                schema_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        binding = self.session.get(PoseModelSchemaBinding, model.id)
        if binding is None:
            schema = PoseLandmarkSchema(
                project_id=model.project_id,
                name=f"{model.display_name} pose landmarks",
            )
            self.session.add(schema)
            self.session.flush()
            schema_revision = PoseLandmarkSchemaRevision(
                schema_id=schema.id,
                revision=1,
                schema_version="pose-landmarks-0001",
                groups_json=groups,
                expanded_labels_json=expanded_labels,
                keypoint_count=len(expanded_labels),
                allows_repeated_labels=any(group.count > 1 for group in payload.groups),
                content_hash=content_hash,
            )
            self.session.add(schema_revision)
            self.session.flush()
            binding = PoseModelSchemaBinding(
                model_id=model.id,
                schema_id=schema.id,
                schema_revision=1,
            )
            self.session.add(binding)
        else:
            existing_revision = self.session.scalar(
                select(PoseLandmarkSchemaRevision).where(
                    PoseLandmarkSchemaRevision.schema_id == binding.schema_id,
                    PoseLandmarkSchemaRevision.content_hash == content_hash,
                )
            )
            if existing_revision is None:
                next_revision = (
                    int(
                        self.session.scalar(
                            select(func.max(PoseLandmarkSchemaRevision.revision)).where(
                                PoseLandmarkSchemaRevision.schema_id == binding.schema_id
                            )
                        )
                        or 0
                    )
                    + 1
                )
                existing_revision = PoseLandmarkSchemaRevision(
                    schema_id=binding.schema_id,
                    revision=next_revision,
                    schema_version="pose-landmarks-0001",
                    groups_json=groups,
                    expanded_labels_json=expanded_labels,
                    keypoint_count=len(expanded_labels),
                    allows_repeated_labels=any(
                        group.count > 1 for group in payload.groups
                    ),
                    content_hash=content_hash,
                )
                self.session.add(existing_revision)
                self.session.flush()
            binding.schema_revision = existing_revision.revision

        metadata["pose_landmark_schema"] = {
            **schema_payload,
            "schema_id": binding.schema_id,
            "schema_revision": binding.schema_revision,
            "content_hash": content_hash,
        }
        model.metadata_json = metadata
        self.session.commit()
        self.session.refresh(model)
        return ModelRegistrationResponse.model_validate(model)

    def create_inference_job(
        self,
        project_id: str,
        payload: InferenceJobCreateRequest,
    ) -> JobResponse:
        project = self._project(project_id)
        model = self._model(payload.model_id)
        compatible = model.project_id == project.id and (
            (model.purpose == "detector" and model.task == "detect")
            or (model.purpose == "segmenter" and model.task == "segment")
            or (
                model.purpose == SEMANTIC_MODEL_PURPOSE and model.task == SEMANTIC_SEGMENTATION_TASK
            )
        )
        if not compatible:
            raise ValidationError(
                "Inference jobs require a compatible detector, instance segmenter, or "
                "semantic segmenter from the same project"
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
