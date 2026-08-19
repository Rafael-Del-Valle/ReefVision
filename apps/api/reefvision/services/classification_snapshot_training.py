"""Queue classifier training directly from immutable classification dataset snapshots."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ClassificationDatasetSample,
    ClassificationDatasetSnapshot,
    Job,
    ModelRegistration,
    TrainingRun,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.classification import (
    CLASSIFICATION_TASK,
    CLASSIFIER_PURPOSE,
    ULTRALYTICS_PROVIDER_ID,
)
from reefvision.schemas.classification_datasets import (
    ClassificationSnapshotTrainingRequest,
    ClassificationSnapshotTrainingResponse,
)
from reefvision.storage.datasets import canonical_json_sha256


class ClassificationSnapshotTrainingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def queue(
        self,
        project_id: str,
        snapshot_id: str,
        request: ClassificationSnapshotTrainingRequest,
    ) -> ClassificationSnapshotTrainingResponse:
        snapshot = self.session.get(ClassificationDatasetSnapshot, snapshot_id)
        if snapshot is None or snapshot.project_id != project_id:
            raise NotFoundError("Classification dataset snapshot not found in this project")
        if snapshot.status != "complete":
            raise ValidationError("Only complete immutable classification snapshots may train")
        if snapshot.cardinality != "single":
            raise ValidationError(
                "Ultralytics classification training currently requires a single-label snapshot; "
                "multi-label snapshots remain valid for review/export but need a multi-label provider"
            )
        samples = list(
            self.session.scalars(
                select(ClassificationDatasetSample)
                .where(ClassificationDatasetSample.snapshot_id == snapshot.id)
                .order_by(
                    ClassificationDatasetSample.split,
                    ClassificationDatasetSample.group_key,
                    ClassificationDatasetSample.target_key,
                )
            )
        )
        if not samples:
            raise ValidationError("Classification snapshot contains no samples")
        if any(len(list(sample.label_class_ids_json or [])) != 1 for sample in samples):
            raise ValidationError("Every single-label training sample must contain exactly one class")
        represented_classes = {
            str(sample.label_class_ids_json[0])
            for sample in samples
            if sample.label_class_ids_json
        }
        if len(represented_classes) < 2:
            raise ValidationError("Classification training requires at least two represented classes")
        split_counts = {
            split: sum(sample.split == split for sample in samples)
            for split in ("train", "validation", "test")
        }
        if split_counts["train"] == 0:
            raise ValidationError("Classification snapshot requires at least one training sample")

        initial_checkpoint_source = "scratch"
        if request.initial_checkpoint_model_id:
            model = self.session.get(ModelRegistration, request.initial_checkpoint_model_id)
            if (
                model is None
                or model.project_id != project_id
                or model.purpose != CLASSIFIER_PURPOSE
                or model.task != CLASSIFICATION_TASK
            ):
                raise ValidationError(
                    "Initial checkpoint must be a registered classifier from this project"
                )
            initial_checkpoint_source = "registered_model"

        split_manifest = {
            "schema": "reefvision-classification-training-split-v1",
            "snapshot_id": snapshot.id,
            "snapshot_manifest_sha256": snapshot.manifest_sha256,
            "samples": [
                {
                    "sample_id": sample.id,
                    "sample_sha256": sample.sample_sha256,
                    "target_key": sample.target_key,
                    "group_key": sample.group_key,
                    "split": sample.split,
                    "label_class_ids": list(sample.label_class_ids_json or []),
                }
                for sample in samples
            ],
        }
        split_manifest_sha256 = canonical_json_sha256(split_manifest)
        manifest = dict(snapshot.manifest_json or {})
        label_set = dict(manifest.get("label_set") or {})
        label_set_key = str(label_set.get("key") or snapshot.label_set_id)

        run_id = str(uuid4())
        job_id = str(uuid4())
        training_config = {
            "classification_dataset_snapshot_id": snapshot.id,
            "classification_scope": snapshot.target_kind,
            "classification_label_set_id": snapshot.label_set_id,
            "classification_label_set_key": label_set_key,
            "classification_cardinality": snapshot.cardinality,
            "classification_mode": "multiclass",
            "epochs": request.epochs,
            "patience": request.patience,
            "batch": request.batch,
            "imgsz": request.imgsz,
            "minimum_crop_size_px": request.minimum_crop_size_px,
            "padding_fraction": request.padding_fraction,
            "mask_background": request.mask_background,
        }
        run = TrainingRun(
            id=run_id,
            project_id=project_id,
            draft_id=None,
            dataset_version_id=None,
            dataset_manifest_sha256=snapshot.manifest_sha256,
            split_manifest_sha256=split_manifest_sha256,
            task=CLASSIFICATION_TASK,
            catalog_model_id=None,
            provider_id=ULTRALYTICS_PROVIDER_ID,
            architecture=request.architecture,
            initial_checkpoint_source=initial_checkpoint_source,
            initial_checkpoint_model_id=request.initial_checkpoint_model_id,
            resolved_model_asset_id=None,
            resolved_model_checksum=None,
            parameter_registry_version=None,
            selected_preset=None,
            installation_state="ready",
            device=request.device,
            precision=request.precision,
            run_name=request.run_name.strip(),
            notes=request.notes.strip() if request.notes else None,
            random_seed=request.random_seed,
            tiling_config_json={"mode": "none"},
            training_config_json=training_config,
            tuning_config_json={"mode": "disabled"},
            evaluation_config_json={
                "classification_dataset_snapshot_id": snapshot.id,
                "target_kind": snapshot.target_kind,
                "label_set_id": snapshot.label_set_id,
                "label_set_key": label_set_key,
            },
            resource_limits_json={},
            preflight_report_json={
                "status": "ready",
                "source": "classification_dataset_snapshot",
                "snapshot_id": snapshot.id,
                "snapshot_manifest_sha256": snapshot.manifest_sha256,
                "split_manifest_sha256": split_manifest_sha256,
                "split_counts": split_counts,
                "represented_class_count": len(represented_classes),
            },
            draft_snapshot_json={
                "source": "classification_dataset_snapshot",
                "snapshot_id": snapshot.id,
                "snapshot_name": snapshot.name,
                "target_kind": snapshot.target_kind,
                "cardinality": snapshot.cardinality,
                "label_set_id": snapshot.label_set_id,
                "label_set_key": label_set_key,
                "snapshot_manifest_sha256": snapshot.manifest_sha256,
                "split_manifest": split_manifest,
            },
            status="queued",
            stage="queued",
            progress_epoch=0,
            progress_total_epochs=request.epochs,
            metrics_json={},
            metrics_history_json={},
            warnings_json=list(snapshot.warnings_json or []),
            artifact_manifest_json={
                "classification_dataset_snapshot_id": snapshot.id,
                "classification_scope": snapshot.target_kind,
                "classification_label_set_id": snapshot.label_set_id,
                "classification_label_set_key": label_set_key,
                "classification_cardinality": snapshot.cardinality,
                "snapshot_manifest_sha256": snapshot.manifest_sha256,
                "split_manifest_sha256": split_manifest_sha256,
            },
            job_id=job_id,
        )
        job = Job(
            id=job_id,
            project_id=project_id,
            job_type="training",
            status="queued",
            progress_total=max(request.epochs, 1),
            progress_current=0,
            request_json={
                "training_run_id": run_id,
                "task": CLASSIFICATION_TASK,
                "classification_dataset_snapshot_id": snapshot.id,
            },
            result_json={"stage": "queued"},
        )
        self.session.add(run)
        self.session.add(job)
        self.session.commit()
        return ClassificationSnapshotTrainingResponse(
            training_run_id=run.id,
            job_id=job.id,
            project_id=project_id,
            snapshot_id=snapshot.id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            split_manifest_sha256=split_manifest_sha256,
            target_kind=snapshot.target_kind,
            label_set_id=snapshot.label_set_id,
            cardinality=snapshot.cardinality,
            status=run.status,
        )
