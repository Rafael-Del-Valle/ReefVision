"""Classification preview, training, inference, labels, and prediction review."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ClassificationPrediction,
    DatasetVersion,
    ImageAsset,
    ImageLabel,
    Job,
    LabelClass,
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.classification import CLASSIFICATION_TASK, CLASSIFIER_PURPOSE
from reefvision.schemas.classification import (
    ClassificationDatasetClassSummary,
    ClassificationDatasetPreviewResponse,
    ClassificationDatasetRequest,
    ClassificationInferenceRequest,
    ClassificationPredictionPage,
    ClassificationPredictionResponse,
    ClassificationReviewRequest,
    ClassificationTrainingRequest,
    ImageLabelResponse,
    ImageLabelWriteRequest,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.training import TrainingRunResponse
from reefvision.services.semantic_training import SemanticTrainingService
from reefvision.storage.classification_exports import preview_classification_dataset
from reefvision.storage.datasets import canonical_json_sha256


class ClassificationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.training = SemanticTrainingService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _version(self, project_id: str, version_id: str) -> DatasetVersion:
        version = self.session.get(DatasetVersion, version_id)
        if version is None:
            raise NotFoundError("Dataset version not found")
        if version.project_id != project_id:
            raise ValidationError("The dataset version must belong to the selected project")
        if version.status != "complete":
            raise ValidationError("Classification requires a complete immutable dataset version")
        return version

    def preview(
        self,
        project_id: str,
        request: ClassificationDatasetRequest,
    ) -> ClassificationDatasetPreviewResponse:
        self._project(project_id)
        version = self._version(project_id, request.dataset_version_id)
        items = self.training.versions.items_for_version(version.id)
        preview = preview_classification_dataset(
            version,
            items,
            mode=request.mode,
            minimum_crop_size_px=request.minimum_crop_size_px,
        )
        return ClassificationDatasetPreviewResponse(
            dataset_version_id=version.id,
            mode=request.mode,
            minimum_crop_size_px=request.minimum_crop_size_px,
            eligible_crop_count=int(preview["eligible_crop_count"]),
            removed_during_preprocessing_count=int(
                preview["removed_during_preprocessing_count"]
            ),
            missing_state_count=int(preview["missing_state_count"]),
            split_counts={str(key): int(value) for key, value in preview["split_counts"].items()},
            classes=[
                ClassificationDatasetClassSummary.model_validate(item)
                for item in preview["classes"]
            ],
            warnings=[str(item) for item in preview["warnings"]],
        )

    def create_training_run(
        self,
        project_id: str,
        request: ClassificationTrainingRequest,
    ) -> TrainingRunResponse:
        project = self._project(project_id)
        version = self._version(project_id, request.dataset_version_id)
        preview = self.preview(project_id, request)
        if preview.eligible_crop_count <= 0:
            raise ValidationError("No eligible classification crops remain after preprocessing")
        if len([item for item in preview.classes if item.crop_count > 0]) < 2:
            raise ValidationError("Classification training requires at least two eligible classes")
        if preview.split_counts.get("train", 0) <= 0:
            raise ValidationError("The training split contains no eligible classification crops")
        if not request.architecture.casefold().endswith(("-cls.yaml", "-cls.pt", "-cls.pth")):
            raise ValidationError("Choose an installed or trusted Ultralytics classification model")

        split_manifest = [
            {
                "image_id": item.image_id,
                "split": item.split,
                "snapshot_sha256": item.snapshot_sha256,
            }
            for item in self.training.versions.items_for_version(version.id)
        ]
        run = TrainingRun(
            project_id=project.id,
            dataset_version_id=version.id,
            dataset_manifest_sha256=version.manifest_sha256,
            split_manifest_sha256=canonical_json_sha256(split_manifest),
            task=CLASSIFICATION_TASK,
            provider_id="ultralytics",
            architecture=request.architecture,
            initial_checkpoint_source="scratch",
            device=request.device,
            precision=request.precision,
            run_name=request.run_name,
            notes=request.notes,
            random_seed=request.random_seed,
            tiling_config_json={"mode": "none"},
            training_config_json={
                "epochs": request.epochs,
                "patience": request.patience,
                "batch": request.batch,
                "imgsz": request.imgsz,
                "workers": 2,
                "cache": False,
                "amp": request.precision == "amp",
                "val": True,
                "plots": True,
                "classification_mode": request.mode,
                "minimum_crop_size_px": request.minimum_crop_size_px,
                "padding_fraction": request.padding_fraction,
            },
            tuning_config_json={"mode": "disabled"},
            evaluation_config_json={"split": "validation"},
            resource_limits_json={"allowed_devices": [request.device]},
            preflight_report_json=preview.model_dump(mode="json"),
            draft_snapshot_json=request.model_dump(mode="json"),
            status="queued",
            stage="queued",
            progress_total_epochs=request.epochs,
            warnings_json=list(preview.warnings),
        )
        self.session.add(run)
        self.session.flush()
        job = Job(
            project_id=project.id,
            job_type="training",
            status="queued",
            progress_total=request.epochs,
            request_json={"training_run_id": run.id, "training_task": CLASSIFICATION_TASK},
            result_json={"stage": "queued"},
        )
        self.session.add(job)
        self.session.flush()
        run.job_id = job.id
        self.session.commit()
        self.session.refresh(run)
        return self.training._run_response(run)

    def create_inference_job(
        self,
        project_id: str,
        request: ClassificationInferenceRequest,
    ) -> JobResponse:
        project = self._project(project_id)
        model = self.session.get(ModelRegistration, request.model_id)
        if (
            model is None
            or model.project_id != project.id
            or model.purpose != CLASSIFIER_PURPOSE
            or model.task != CLASSIFICATION_TASK
        ):
            raise ValidationError("Choose a registered classifier from this project")
        images = list(
            self.session.scalars(select(ImageAsset).where(ImageAsset.id.in_(request.image_ids)))
        )
        if len(images) != len(set(request.image_ids)):
            raise ValidationError("One or more requested images do not exist")
        if any(image.project_id != project.id for image in images):
            raise ValidationError("All inference images must belong to the selected project")
        job = Job(
            project_id=project.id,
            job_type="classification_inference",
            status="queued",
            progress_total=len(images),
            request_json={
                **request.model_dump(mode="json"),
                "model_task": CLASSIFICATION_TASK,
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def list_predictions(
        self,
        project_id: str,
        *,
        page: int,
        page_size: int,
        image_id: str | None,
        model_id: str | None,
        review_status: str | None,
    ) -> ClassificationPredictionPage:
        self._project(project_id)
        filters = [ClassificationPrediction.project_id == project_id]
        if image_id:
            filters.append(ClassificationPrediction.image_id == image_id)
        if model_id:
            filters.append(ClassificationPrediction.model_id == model_id)
        if review_status:
            filters.append(ClassificationPrediction.review_status == review_status)
        total = int(
            self.session.scalar(
                select(func.count(ClassificationPrediction.id)).where(*filters)
            )
            or 0
        )
        rows = list(
            self.session.scalars(
                select(ClassificationPrediction)
                .where(*filters)
                .order_by(
                    ClassificationPrediction.created_at.desc(),
                    ClassificationPrediction.id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return ClassificationPredictionPage(
            items=[ClassificationPredictionResponse.model_validate(item) for item in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    def review_prediction(
        self,
        prediction_id: str,
        request: ClassificationReviewRequest,
    ) -> ClassificationPredictionResponse:
        prediction = self.session.get(ClassificationPrediction, prediction_id)
        if prediction is None:
            raise NotFoundError("Classification prediction not found")
        if prediction.review_status != "pending":
            raise ConflictError("Only pending classification predictions may be reviewed")
        if request.action == "reject":
            prediction.review_status = "rejected"
            prediction.reviewed_at = datetime.now(UTC)
            self.session.commit()
            self.session.refresh(prediction)
            return ClassificationPredictionResponse.model_validate(prediction)

        annotation = (
            self.session.get(Annotation, prediction.annotation_id)
            if prediction.annotation_id is not None
            else None
        )
        if annotation is None or annotation.deleted_at is not None:
            raise ValidationError("Accepting this crop prediction requires its source annotation")
        target_class_id = request.label_class_id or prediction.label_class_id
        target_class = (
            self.session.get(LabelClass, target_class_id) if target_class_id is not None else None
        )
        if target_class is None or target_class.project_id != prediction.project_id:
            raise ValidationError("Choose a valid project class before accepting this prediction")
        image = self.session.get(ImageAsset, prediction.image_id)
        if image is None:
            raise NotFoundError("Source image not found")
        before = {
            "label_class_id": annotation.label_class_id,
            "source_type": annotation.source_type,
            "source_model_id": annotation.source_model_id,
            "source_prediction_id": annotation.source_prediction_id,
            "revision": annotation.revision,
        }
        annotation.label_class_id = target_class.id
        annotation.source_type = "accepted_prediction"
        annotation.source_model_id = prediction.model_id
        annotation.source_prediction_id = prediction.id
        annotation.provenance_json = {
            **dict(annotation.provenance_json or {}),
            "classification_prediction_id": prediction.id,
            "classification_mode": prediction.classification_mode,
            "classification_confidence": prediction.confidence,
        }
        annotation.revision += 1
        image.annotation_revision += 1
        self.session.add(
            AnnotationEvent(
                annotation_id=annotation.id,
                image_id=image.id,
                event_type="class_changed",
                before_json=before,
                after_json={
                    "label_class_id": annotation.label_class_id,
                    "source_type": annotation.source_type,
                    "source_model_id": annotation.source_model_id,
                    "source_prediction_id": annotation.source_prediction_id,
                    "revision": annotation.revision,
                },
                actor="local_user",
            )
        )
        prediction.review_status = "accepted"
        prediction.accepted_label_class_id = target_class.id
        prediction.reviewed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(prediction)
        return ClassificationPredictionResponse.model_validate(prediction)

    def list_image_labels(self, image_id: str) -> list[ImageLabelResponse]:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        labels = list(
            self.session.scalars(
                select(ImageLabel)
                .where(ImageLabel.image_id == image.id)
                .order_by(ImageLabel.label_set, ImageLabel.created_at)
            )
        )
        return [ImageLabelResponse.model_validate(item) for item in labels]

    def add_image_label(
        self,
        image_id: str,
        request: ImageLabelWriteRequest,
    ) -> ImageLabelResponse:
        image = self.session.get(ImageAsset, image_id)
        label_class = self.session.get(LabelClass, request.label_class_id)
        if image is None:
            raise NotFoundError("Image not found")
        if label_class is None or label_class.project_id != image.project_id:
            raise ValidationError("Image labels must use a class from the same project")
        existing = self.session.scalar(
            select(ImageLabel).where(
                ImageLabel.image_id == image.id,
                ImageLabel.label_class_id == label_class.id,
                ImageLabel.label_set == request.label_set,
            )
        )
        if existing is not None:
            existing.status = request.status
            self.session.commit()
            self.session.refresh(existing)
            return ImageLabelResponse.model_validate(existing)
        label = ImageLabel(
            image_id=image.id,
            label_class_id=label_class.id,
            label_set=request.label_set,
            source_type="human",
            status=request.status,
        )
        self.session.add(label)
        self.session.commit()
        self.session.refresh(label)
        return ImageLabelResponse.model_validate(label)

    def delete_image_label(self, label_id: str) -> None:
        label = self.session.get(ImageLabel, label_id)
        if label is None:
            raise NotFoundError("Image label not found")
        self.session.delete(label)
        self.session.commit()
