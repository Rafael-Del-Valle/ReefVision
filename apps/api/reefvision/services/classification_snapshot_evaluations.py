"""Queue reproducible held-out evaluation against immutable classification snapshots."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationDatasetSample,
    ClassificationDatasetSnapshot,
    Job,
    ModelRegistration,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.classification import CLASSIFICATION_TASK, CLASSIFIER_PURPOSE
from reefvision.schemas.classification_datasets import (
    ClassificationSnapshotEvaluationQueueResponse,
    ClassificationSnapshotEvaluationRequest,
)
from reefvision.services.generalized_classification_jobs import _normalized_scope
from reefvision.storage.models import resolve_verified_model_path


class ClassificationSnapshotEvaluationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def queue(
        self,
        project_id: str,
        snapshot_id: str,
        request: ClassificationSnapshotEvaluationRequest,
    ) -> ClassificationSnapshotEvaluationQueueResponse:
        snapshot = self.session.get(ClassificationDatasetSnapshot, snapshot_id)
        if snapshot is None or snapshot.project_id != project_id:
            raise NotFoundError("Classification dataset snapshot not found in this project")
        if snapshot.status != "complete":
            raise ValidationError("Only complete immutable classification snapshots may evaluate")
        if snapshot.cardinality != "single":
            raise ValidationError(
                "Held-out confusion-matrix evaluation currently requires a single-label snapshot"
            )
        model = self.session.get(ModelRegistration, request.model_id)
        if (
            model is None
            or model.project_id != project_id
            or model.purpose != CLASSIFIER_PURPOSE
            or model.task != CLASSIFICATION_TASK
        ):
            raise ValidationError("Choose a registered classifier from this project")
        resolve_verified_model_path(
            self.settings,
            model.managed_path,
            expected_sha256=model.sha256,
        )

        manifest = dict(snapshot.manifest_json or {})
        label_set = dict(manifest.get("label_set") or {})
        snapshot_label_set_key = str(label_set.get("key") or snapshot.label_set_id)
        model_metadata = dict(model.metadata_json or {})
        class_map = dict(model.class_map_json or {})
        trained_scope = _normalized_scope(
            model_metadata.get("classification_scope") or class_map.get("classification_scope")
        )
        scope_locked = bool(
            model_metadata.get("classification_scope_locked")
            or class_map.get("classification_scope_locked")
        )
        if trained_scope and trained_scope != "unknown" and trained_scope != snapshot.target_kind:
            raise ValidationError(
                f"Classifier target kind {trained_scope!r} does not match snapshot target kind "
                f"{snapshot.target_kind!r}"
            )
        trained_label_set = str(
            model_metadata.get("classification_label_set_key")
            or class_map.get("classification_label_set_key")
            or ""
        ).strip()
        if scope_locked and trained_label_set and trained_label_set != snapshot_label_set_key:
            raise ValidationError(
                f"Classifier label set {trained_label_set!r} does not match snapshot label set "
                f"{snapshot_label_set_key!r}"
            )

        mapping = class_map.get("mapping", {})
        if not isinstance(mapping, dict) or not mapping:
            raise ValidationError("Registered classifier is missing its project-class mapping")
        mapped_class_ids = {str(value) for value in mapping.values() if value}
        snapshot_class_ids = {
            str(item.get("id"))
            for item in snapshot.class_map_json or []
            if isinstance(item, dict) and item.get("id")
        }
        missing_classes = sorted(snapshot_class_ids - mapped_class_ids)
        if missing_classes:
            raise ValidationError(
                "Classifier does not map every snapshot class; missing project class ids: "
                + ", ".join(missing_classes)
            )

        sample_count = int(
            self.session.scalar(
                select(func.count(ClassificationDatasetSample.id)).where(
                    ClassificationDatasetSample.snapshot_id == snapshot.id,
                    ClassificationDatasetSample.split == request.split,
                )
            )
            or 0
        )
        if sample_count <= 0:
            raise ValidationError(
                f"Classification snapshot has no samples in its {request.split!r} split"
            )

        job = Job(
            project_id=project_id,
            job_type="classification_snapshot_evaluation",
            status="queued",
            progress_total=sample_count,
            progress_current=0,
            request_json={
                **request.model_dump(mode="json"),
                "snapshot_id": snapshot.id,
                "snapshot_manifest_sha256": snapshot.manifest_sha256,
                "model_checksum": model.sha256,
                "snapshot_target_kind": snapshot.target_kind,
                "snapshot_label_set_id": snapshot.label_set_id,
                "snapshot_label_set_key": snapshot_label_set_key,
            },
            result_json={"stage": "queued"},
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ClassificationSnapshotEvaluationQueueResponse(
            job_id=job.id,
            project_id=project_id,
            snapshot_id=snapshot.id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            model_id=model.id,
            model_checksum=model.sha256,
            split=request.split,
            sample_count=sample_count,
            status=job.status,
        )
