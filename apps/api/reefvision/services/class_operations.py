"""Services for class reassignment and distinct reassign-delete workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    DatasetVersion,
    ImageAsset,
    ImageLabel,
    LabelClass,
    MaskAnnotation,
    MaskAnnotationEvent,
    ModelRegistration,
    PredictionProposal,
    Project,
    QualityControlIssue,
    ReviewQueueItem,
)
from reefvision.db.models.class_operation import ClassOperation
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.repositories.class_operations import ClassOperationRepository
from reefvision.repositories.projects import LabelClassRepository, ProjectRepository
from reefvision.schemas.class_operations import (
    ClassOperationClassSnapshotResponse,
    ClassOperationCompatibilityImpactResponse,
    ClassOperationExecuteRequest,
    ClassOperationPlanResponse,
    ClassOperationPreviewRequest,
    ClassOperationRecordGroupResponse,
    ClassOperationResponse,
)
from reefvision.schemas.projects import LabelClassUsageResponse
from reefvision.services.annotations import annotation_snapshot
from reefvision.services.projects import (
    UNHANDLED_CLASS_REFERENCE_CATEGORIES,
    USAGE_CATEGORY_META,
    ProjectService,
)
from reefvision.storage.identity import get_local_user_identity

MUTABLE_QC_STATUSES = {"open", "acknowledged"}
MUTABLE_REVIEW_STATES = {"pending", "in_progress"}
MUTABLE_PREDICTION_STATUSES = {"pending"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _contains_label_class_reference(payload: object, class_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("label_class_id") == class_id


def _replace_class_id_list(
    values: list[str], source_class_id: str, target_class_id: str
) -> list[str]:
    replaced: list[str] = []
    seen: set[str] = set()
    for value in values:
        next_value = target_class_id if value == source_class_id else value
        if next_value in seen:
            continue
        replaced.append(next_value)
        seen.add(next_value)
    return replaced


def _label_class_snapshot(label_class: LabelClass) -> dict[str, Any]:
    return {
        "id": label_class.id,
        "name": label_class.name,
        "class_index": label_class.class_index,
        "display_order": label_class.display_order,
        "display_color": label_class.display_color,
        "scientific_name": label_class.scientific_name,
        "state_name": label_class.state_name,
        "description": label_class.description,
        "archived_at": label_class.archived_at.isoformat() if label_class.archived_at else None,
    }


def _class_biological_identity(label_class: LabelClass) -> dict[str, Any]:
    """Reviewed source/target semantics that must stay stable until execution."""
    return {
        "id": label_class.id,
        "name": label_class.name,
        "class_index": label_class.class_index,
        "scientific_name": label_class.scientific_name,
        "state_name": label_class.state_name,
        "is_active": label_class.is_active,
        "archived_at": label_class.archived_at.isoformat() if label_class.archived_at else None,
    }


@dataclass(slots=True)
class OperationPlan:
    mutable_records: list[ClassOperationRecordGroupResponse]
    protected_records: list[ClassOperationRecordGroupResponse]
    blocking_records: list[ClassOperationRecordGroupResponse]
    compatibility_impacts: list[ClassOperationCompatibilityImpactResponse]
    warnings: list[str]
    blockers: list[str]
    # Bind approval to the actual class memberships and mutable review state,
    # not just to the unchanged IDs of QC and review-queue records.
    review_reference_evidence: dict[str, list[dict[str, Any]]]
    observation_reference_evidence: dict[str, list[dict[str, Any]]]
    # Immutable dataset and local model compatibility evidence must not drift.
    compatibility_reference_evidence: dict[str, list[dict[str, Any]]]


class ClassOperationsService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.classes = LabelClassRepository(session)
        self.operations = ClassOperationRepository(session)
        self.project_service = ProjectService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _class(self, project_id: str, class_id: str) -> LabelClass:
        label_class = self.classes.get(class_id)
        if label_class is None or label_class.project_id != project_id:
            raise NotFoundError("Label class not found")
        return label_class

    def _operation(self, operation_id: str) -> ClassOperation:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise NotFoundError("Class operation not found")
        return operation

    def usage_for_class(self, project_id: str, class_id: str) -> LabelClassUsageResponse:
        label_class = self._class(project_id, class_id)
        return self.project_service._usage_response(
            label_class,
            self.project_service._usage_snapshot(label_class),
        )

    def _group(
        self, key: str, label: str, record_ids: list[str]
    ) -> ClassOperationRecordGroupResponse:
        return ClassOperationRecordGroupResponse(
            key=key,
            label=label,
            count=len(record_ids),
            record_ids=record_ids,
        )

    def _compatibility_impacts(
        self,
        *,
        dataset_version_ids: list[str],
        model_registration_ids: list[str],
    ) -> list[ClassOperationCompatibilityImpactResponse]:
        impacts: list[ClassOperationCompatibilityImpactResponse] = []
        if dataset_version_ids:
            impacts.append(
                ClassOperationCompatibilityImpactResponse(
                    key="dataset_versions",
                    label="Immutable dataset versions",
                    status="Historical class only",
                    message=(
                        "Immutable dataset versions keep their original class map and are not "
                        "rewritten by reassignment or reassign-delete."
                    ),
                    record_ids=dataset_version_ids,
                )
            )
        if model_registration_ids:
            impacts.append(
                ClassOperationCompatibilityImpactResponse(
                    key="model_registrations",
                    label="Registered model class maps",
                    status="Compatible with explicit remapping",
                    message=(
                        "Registered model class maps remain unchanged. Create an explicit "
                        "compatibility mapping before training, inference, import, or export "
                        "workflows rely on the old class."
                    ),
                    record_ids=model_registration_ids,
                )
            )
        return impacts

    def _unhandled_reference_groups(
        self, source_class: LabelClass
    ) -> list[ClassOperationRecordGroupResponse]:
        """Expose exact mask/classification records that this operation cannot migrate.

        A blocked preview must identify the preserved scientific record IDs, not
        merely report aggregate counts. This evidence also enters the saved
        preview checksum and makes changes invalidate researcher approval.
        """
        masks = list(
            self.session.scalars(
                select(MaskAnnotation).where(MaskAnnotation.label_class_id == source_class.id)
            )
        )
        mask_events = list(
            self.session.scalars(
                select(MaskAnnotationEvent)
                .join(ImageAsset, ImageAsset.id == MaskAnnotationEvent.image_id)
                .where(ImageAsset.project_id == source_class.project_id)
            )
        )
        image_labels = list(
            self.session.scalars(
                select(ImageLabel).where(ImageLabel.label_class_id == source_class.id)
            )
        )
        record_ids = {
            "mask_annotations_active": sorted(item.id for item in masks if item.deleted_at is None),
            "mask_annotations_deleted": sorted(
                item.id for item in masks if item.deleted_at is not None
            ),
            "mask_annotation_history": sorted(
                item.id
                for item in mask_events
                if _contains_label_class_reference(item.before_json, source_class.id)
                or _contains_label_class_reference(item.after_json, source_class.id)
            ),
            "image_labels_active": sorted(
                item.id for item in image_labels if item.deleted_at is None
            ),
            "image_labels_deleted": sorted(
                item.id for item in image_labels if item.deleted_at is not None
            ),
        }
        return [
            self._group(key, USAGE_CATEGORY_META[key][0], record_ids[key])
            for key in UNHANDLED_CLASS_REFERENCE_CATEGORIES
            if record_ids[key]
        ]

    def _plan(
        self,
        *,
        operation_type: str,
        source_class: LabelClass,
        target_class: LabelClass,
    ) -> OperationPlan:
        annotations = list(
            self.session.scalars(
                select(Annotation).where(Annotation.label_class_id == source_class.id)
            )
        )
        active_annotation_ids = sorted(
            annotation.id for annotation in annotations if annotation.deleted_at is None
        )
        deleted_annotation_ids = sorted(
            annotation.id for annotation in annotations if annotation.deleted_at is not None
        )

        annotation_event_ids = sorted(
            event.id
            for event in self.session.scalars(
                select(AnnotationEvent)
                .join(ImageAsset, ImageAsset.id == AnnotationEvent.image_id)
                .where(ImageAsset.project_id == source_class.project_id)
            )
            if _contains_label_class_reference(event.before_json, source_class.id)
            or _contains_label_class_reference(event.after_json, source_class.id)
        )

        prediction_proposals = list(
            self.session.scalars(
                select(PredictionProposal).where(
                    PredictionProposal.project_id == source_class.project_id,
                    PredictionProposal.label_class_id == source_class.id,
                )
            )
        )
        mutable_prediction_ids = sorted(
            proposal.id
            for proposal in prediction_proposals
            if proposal.review_status in MUTABLE_PREDICTION_STATUSES
        )
        protected_prediction_ids = sorted(
            proposal.id
            for proposal in prediction_proposals
            if proposal.review_status not in MUTABLE_PREDICTION_STATUSES
        )

        quality_control_issues = list(
            self.session.scalars(
                select(QualityControlIssue).where(
                    QualityControlIssue.project_id == source_class.project_id
                )
            )
        )
        mutable_qc_issue_ids = sorted(
            issue.id
            for issue in quality_control_issues
            if source_class.id in issue.class_ids_json and issue.status in MUTABLE_QC_STATUSES
        )
        protected_qc_issue_ids = sorted(
            issue.id
            for issue in quality_control_issues
            if source_class.id in issue.class_ids_json and issue.status not in MUTABLE_QC_STATUSES
        )

        review_queue_items = list(
            self.session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.project_id == source_class.project_id)
            )
        )
        mutable_review_queue_ids = sorted(
            item.id
            for item in review_queue_items
            if source_class.id in item.label_class_ids_json
            and item.review_state in MUTABLE_REVIEW_STATES
        )
        protected_review_queue_ids = sorted(
            item.id
            for item in review_queue_items
            if source_class.id in item.label_class_ids_json
            and item.review_state not in MUTABLE_REVIEW_STATES
        )

        dataset_versions = sorted(
            (
                version
                for version in self.session.scalars(
                    select(DatasetVersion).where(
                        DatasetVersion.project_id == source_class.project_id
                    )
                )
                if any(entry.get("id") == source_class.id for entry in version.class_map_json)
            ),
            key=lambda version: version.id,
        )
        dataset_version_ids = [version.id for version in dataset_versions]

        model_registrations = sorted(
            (
                model
                for model in self.session.scalars(
                    select(ModelRegistration).where(
                        ModelRegistration.project_id == source_class.project_id
                    )
                )
                if source_class.id
                in {
                    value
                    for value in (model.class_map_json.get("mapping") or {}).values()
                    if isinstance(value, str)
                }
            ),
            key=lambda model: model.id,
        )
        model_registration_ids = [model.id for model in model_registrations]

        mutable_records = [
            self._group("annotations_active", "Active annotations", active_annotation_ids),
            self._group(
                "prediction_proposals_pending",
                "Pending prediction proposals",
                mutable_prediction_ids,
            ),
            self._group(
                "quality_control_issues_open",
                "Open quality-control issues",
                mutable_qc_issue_ids,
            ),
            self._group(
                "review_queue_items_open",
                "Open review-queue items",
                mutable_review_queue_ids,
            ),
        ]
        protected_records = [
            self._group("annotations_deleted", "Deleted annotations", deleted_annotation_ids),
            self._group("annotation_history", "Annotation history events", annotation_event_ids),
            self._group(
                "prediction_proposals_historical",
                "Historical prediction proposals",
                protected_prediction_ids,
            ),
            self._group(
                "quality_control_issues_closed",
                "Closed quality-control issues",
                protected_qc_issue_ids,
            ),
            self._group(
                "review_queue_items_closed",
                "Closed review-queue items",
                protected_review_queue_ids,
            ),
            self._group("dataset_versions", "Immutable dataset versions", dataset_version_ids),
            self._group(
                "model_registrations",
                "Registered model class maps",
                model_registration_ids,
            ),
        ]

        unsupported_groups = self._unhandled_reference_groups(source_class)
        protected_records.extend(unsupported_groups)

        warnings: list[str] = []
        blockers: list[str] = []
        blocking_records: list[ClassOperationRecordGroupResponse] = []
        compatibility_impacts = self._compatibility_impacts(
            dataset_version_ids=dataset_version_ids,
            model_registration_ids=model_registration_ids,
        )

        if source_class.archived_at is not None:
            warnings.append(
                "The source class is already archived. Reassignment still "
                "preserves immutable history."
            )
        if target_class.archived_at is not None or not target_class.is_active:
            blockers.append("Restore the target class before reassigning records into it.")

        if dataset_version_ids:
            warnings.append(
                "Immutable dataset versions keep their original class map for reproducibility."
            )
        if model_registration_ids:
            warnings.append(
                "Registered model class maps remain unchanged and may need explicit remapping."
            )
        if annotation_event_ids:
            warnings.append("Historical annotation events remain unchanged for auditability.")
        if unsupported_groups:
            warnings.append(
                "Mask and image-level classification records remain attached to the "
                "source class; reassignment does not migrate these modalities."
            )

        if operation_type == "reassign_delete":
            # Physical deletion would cascade through mask and image-label FKs.
            # This workflow cannot reassign those modalities, so fail at preview
            # and again before execution rather than silently destroying them.
            source_usage = self.project_service._usage_snapshot(source_class)
            unsupported_by_key = {group.key: group for group in unsupported_groups}
            for key in UNHANDLED_CLASS_REFERENCE_CATEGORIES:
                count = source_usage.counts[key]
                group = unsupported_by_key.get(key)
                if count != (group.count if group is not None else 0):
                    blockers.append(
                        f"{USAGE_CATEGORY_META[key][0]} changed during preview. "
                        "Refresh the record inventory before continuing."
                    )
                if count or group is not None:
                    blockers.append(
                        f"{USAGE_CATEGORY_META[key][0]} ({count}) block physical class deletion; "
                        "the reassign-delete workflow does not handle these records."
                    )
                    if group is not None:
                        blocking_records.append(group)
            if deleted_annotation_ids:
                blockers.append(
                    "Deleted annotations still reference this class and would be "
                    "removed by a hard delete."
                )
                blocking_records.append(
                    self._group(
                        "annotations_deleted",
                        "Deleted annotations block physical deletion",
                        deleted_annotation_ids,
                    )
                )
            if protected_prediction_ids:
                blockers.append(
                    "Historical prediction proposals still reference this class and "
                    "would lose their class link if the source class were deleted."
                )
                blocking_records.append(
                    self._group(
                        "prediction_proposals_historical",
                        "Historical prediction proposals block physical deletion",
                        protected_prediction_ids,
                    )
                )

        return OperationPlan(
            mutable_records=[group for group in mutable_records if group.count > 0],
            protected_records=[group for group in protected_records if group.count > 0],
            blocking_records=blocking_records,
            compatibility_impacts=compatibility_impacts,
            warnings=warnings,
            blockers=blockers,
            observation_reference_evidence={
                "annotations": [
                    {
                        "id": annotation.id,
                        "image_id": annotation.image_id,
                        "revision": annotation.revision,
                        "bounds_px": [
                            annotation.x_min,
                            annotation.y_min,
                            annotation.x_max,
                            annotation.y_max,
                        ],
                    }
                    for annotation in sorted(annotations, key=lambda item: item.id)
                ],
                "prediction_proposals": [
                    {
                        "id": proposal.id,
                        "image_id": proposal.image_id,
                        "model_id": proposal.model_id,
                        "model_checksum": proposal.model_checksum,
                        "review_status": proposal.review_status,
                        "predicted_label": proposal.predicted_label,
                        "predicted_index": proposal.predicted_index,
                        "confidence": proposal.confidence,
                        "geometry_kind": proposal.geometry_kind,
                        "bounds_px": [
                            proposal.x_min,
                            proposal.y_min,
                            proposal.x_max,
                            proposal.y_max,
                        ],
                        "polygon_sha256": (
                            hashlib.sha256(
                                json.dumps(
                                    proposal.polygon_json,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ).encode("utf-8")
                            ).hexdigest()
                            if proposal.polygon_json is not None
                            else None
                        ),
                        "mask_content_sha256": proposal.mask_content_sha256,
                    }
                    for proposal in sorted(prediction_proposals, key=lambda item: item.id)
                ],
            },
            compatibility_reference_evidence={
                "dataset_versions": [
                    {
                        "id": version.id,
                        "class_map": version.class_map_json,
                        "manifest_sha256": version.manifest_sha256,
                    }
                    for version in dataset_versions
                ],
                "model_registrations": [
                    {
                        "id": model.id,
                        "class_map": model.class_map_json,
                        "weights_sha256": model.sha256,
                    }
                    for model in model_registrations
                ],
            },
            review_reference_evidence={
                "quality_control_issues": [
                    {
                        "id": issue.id,
                        "status": issue.status,
                        "class_ids": list(issue.class_ids_json),
                    }
                    for issue in sorted(quality_control_issues, key=lambda item: item.id)
                    if source_class.id in issue.class_ids_json
                ],
                "review_queue_items": [
                    {
                        "id": item.id,
                        "state": item.review_state,
                        "class_ids": list(item.label_class_ids_json),
                    }
                    for item in sorted(review_queue_items, key=lambda item: item.id)
                    if source_class.id in item.label_class_ids_json
                ],
            },
        )

    def _plan_checksum(
        self,
        *,
        operation_type: str,
        source_class: LabelClass,
        target_class: LabelClass,
        plan: OperationPlan,
    ) -> str:
        payload = {
            "operation_type": operation_type,
            "project_id": source_class.project_id,
            "source_class_id": source_class.id,
            "target_class_id": target_class.id,
            # Counts and reference IDs alone cannot preserve biological meaning.
            "source_class_biological_identity": _class_biological_identity(source_class),
            "target_class_biological_identity": _class_biological_identity(target_class),
            "mutable_records": [
                {"key": item.key, "record_ids": item.record_ids} for item in plan.mutable_records
            ],
            "protected_records": [
                {"key": item.key, "record_ids": item.record_ids} for item in plan.protected_records
            ],
            "blocking_records": [
                {"key": item.key, "record_ids": item.record_ids} for item in plan.blocking_records
            ],
            "compatibility_impacts": [
                {
                    "key": item.key,
                    "status": item.status,
                    "record_ids": item.record_ids,
                }
                for item in plan.compatibility_impacts
            ],
            "warnings": plan.warnings,
            "blockers": plan.blockers,
            "review_reference_evidence": plan.review_reference_evidence,
            "observation_reference_evidence": plan.observation_reference_evidence,
            "compatibility_reference_evidence": plan.compatibility_reference_evidence,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _response(self, operation: ClassOperation) -> ClassOperationResponse:
        plan = operation.plan_json
        return ClassOperationResponse(
            id=operation.id,
            project_id=operation.project_id,
            source_class_id=operation.source_class_id,
            target_class_id=operation.target_class_id,
            operation_type=operation.operation_type,
            status=operation.status,
            preview_checksum=operation.preview_checksum,
            requested_by_identity=operation.requested_by_identity,
            source_class=ClassOperationClassSnapshotResponse.model_validate(
                operation.source_class_snapshot_json
            ),
            target_class=(
                ClassOperationClassSnapshotResponse.model_validate(
                    operation.target_class_snapshot_json
                )
                if operation.target_class_snapshot_json
                else None
            ),
            plan=ClassOperationPlanResponse.model_validate(plan),
            affected_counts=[
                ClassOperationRecordGroupResponse.model_validate(item)
                for item in operation.affected_counts_json
            ],
            protected_reference_counts=[
                ClassOperationRecordGroupResponse.model_validate(item)
                for item in operation.protected_reference_counts_json
            ],
            warnings=operation.warnings_json,
            failures=operation.failures_json,
            rollback_result=operation.rollback_result_json,
            final_state=operation.final_state,
            notes=operation.notes,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            started_at=operation.started_at,
            completed_at=operation.completed_at,
        )

    def _create_preview(
        self,
        *,
        operation_type: str,
        project_id: str,
        class_id: str,
        payload: ClassOperationPreviewRequest,
    ) -> ClassOperationResponse:
        self._project(project_id)
        source_class = self._class(project_id, class_id)
        target_class = self._class(project_id, payload.target_class_id)
        if source_class.id == target_class.id:
            raise ConflictError("Choose a different target class")
        if not target_class.is_active or target_class.archived_at is not None:
            raise ConflictError("Restore the target class before reassigning into it")

        plan = self._plan(
            operation_type=operation_type,
            source_class=source_class,
            target_class=target_class,
        )
        checksum = self._plan_checksum(
            operation_type=operation_type,
            source_class=source_class,
            target_class=target_class,
            plan=plan,
        )
        user_identity = get_local_user_identity(self.settings)
        operation = ClassOperation(
            project_id=project_id,
            source_class_id=source_class.id,
            target_class_id=target_class.id,
            operation_type=operation_type,
            status="previewed",
            preview_checksum=checksum,
            requested_by_identity=user_identity,
            source_class_snapshot_json=_label_class_snapshot(source_class),
            target_class_snapshot_json=_label_class_snapshot(target_class),
            plan_json=ClassOperationPlanResponse(
                mutable_records=plan.mutable_records,
                protected_records=plan.protected_records,
                blocking_records=plan.blocking_records,
                compatibility_impacts=plan.compatibility_impacts,
                warnings=plan.warnings,
                blockers=plan.blockers,
            ).model_dump(mode="json"),
            warnings_json=plan.warnings,
            notes=payload.notes,
        )
        self.operations.add(operation)
        self.session.commit()
        self.session.refresh(operation)
        return self._response(operation)

    def preview_reassign(
        self, project_id: str, class_id: str, payload: ClassOperationPreviewRequest
    ) -> ClassOperationResponse:
        return self._create_preview(
            operation_type="reassign",
            project_id=project_id,
            class_id=class_id,
            payload=payload,
        )

    def preview_reassign_delete(
        self, project_id: str, class_id: str, payload: ClassOperationPreviewRequest
    ) -> ClassOperationResponse:
        return self._create_preview(
            operation_type="reassign_delete",
            project_id=project_id,
            class_id=class_id,
            payload=payload,
        )

    def get_operation(self, operation_id: str) -> ClassOperationResponse:
        return self._response(self._operation(operation_id))

    def _execute(
        self,
        *,
        operation_type: str,
        project_id: str,
        class_id: str,
        payload: ClassOperationExecuteRequest,
    ) -> ClassOperationResponse:
        self._project(project_id)
        operation = self._operation(payload.operation_id)
        if operation.project_id != project_id or operation.source_class_id != class_id:
            raise ConflictError("This operation does not belong to the requested project class")
        if operation.operation_type != operation_type:
            raise ConflictError("Use the matching execution endpoint for this preview")
        if operation.preview_checksum != payload.preview_checksum:
            raise ConflictError("The preview checksum does not match the stored operation plan")
        if operation.status != "previewed":
            raise ConflictError("Only previewed class operations can be executed")
        # The checksum approves the plan, not a transfer of researcher authority.
        # A changed local identity must produce a fresh reviewed preview.
        if operation.requested_by_identity != get_local_user_identity(self.settings):
            raise ConflictError(
                "Only the local researcher who created this preview can execute it. "
                "Generate a new preview under the current local identity."
            )
        if operation.target_class_id is None:
            raise ConflictError("A target class is required")

        source_class = self._class(project_id, class_id)
        target_class = self._class(project_id, operation.target_class_id)

        # Claim this approved preview with a conditional write BEFORE rebuilding
        # its evidence. SQLite holds the writer lock until our final commit, so
        # no other local editor can change the evidence after validation or
        # execute the same preview concurrently. The previous early "running"
        # commit released that lock and exposed partial operation state.
        claim = self.session.execute(
            update(ClassOperation)
            .where(
                ClassOperation.id == operation.id,
                ClassOperation.status == "previewed",
            )
            .values(status="running")
        )
        if claim.rowcount != 1:
            self.session.rollback()
            raise ConflictError("This class operation was already claimed. Reload its status.")
        # The earlier class reads happened before the write lock. Force fresh
        # evidence reads under the claimed SQLite transaction.
        self.session.expire(source_class)
        self.session.expire(target_class)
        current_plan = self._plan(
            operation_type=operation_type,
            source_class=source_class,
            target_class=target_class,
        )
        current_checksum = self._plan_checksum(
            operation_type=operation_type,
            source_class=source_class,
            target_class=target_class,
            plan=current_plan,
        )
        if current_checksum != operation.preview_checksum:
            operation.status = "failed"
            operation.failures_json = [
                "The project changed after preview. Generate a fresh preview before executing."
            ]
            operation.rollback_result_json = {"rolled_back": False, "reason": "preview_stale"}
            operation.final_state = "preview_stale"
            operation.completed_at = _utc_now()
            self.session.commit()
            raise ConflictError("The preview is stale. Preview the class operation again.")

        if current_plan.blockers:
            operation.status = "failed"
            operation.failures_json = current_plan.blockers
            operation.rollback_result_json = {"rolled_back": False, "reason": "blocking_records"}
            operation.final_state = "blocked"
            operation.completed_at = _utc_now()
            operation.plan_json = ClassOperationPlanResponse(
                mutable_records=current_plan.mutable_records,
                protected_records=current_plan.protected_records,
                blocking_records=current_plan.blocking_records,
                compatibility_impacts=current_plan.compatibility_impacts,
                warnings=current_plan.warnings,
                blockers=current_plan.blockers,
            ).model_dump(mode="json")
            self.session.commit()
            raise ConflictError("This class operation is blocked. Review the blocking records.")

        if payload.notes is not None:
            operation.notes = payload.notes

        # A preflight rejection is not an attempted scientific execution.
        # Record the start only after the locked evidence/review gate passes.
        started_at = _utc_now()
        operation.started_at = started_at

        # Status, biological record updates, append-only events, and deletion
        # (when approved) commit atomically; no intermediate "running" commit.
        try:
            affected_counts: dict[str, int] = {}

            annotations = list(
                self.session.scalars(
                    select(Annotation)
                    .where(
                        Annotation.label_class_id == source_class.id,
                        Annotation.deleted_at.is_(None),
                    )
                    .order_by(Annotation.created_at, Annotation.id)
                )
            )
            for annotation in annotations:
                before = annotation_snapshot(annotation)
                annotation.label_class_id = target_class.id
                annotation.revision += 1
                self.session.add(
                    AnnotationEvent(
                        annotation_id=annotation.id,
                        image_id=annotation.image_id,
                        event_type=(
                            "class_reassigned"
                            if operation_type == "reassign"
                            else "class_reassigned_for_delete"
                        ),
                        before_json=before,
                        after_json=annotation_snapshot(annotation),
                        actor=operation.requested_by_identity,
                    )
                )
                affected_counts["annotations_active"] = (
                    affected_counts.get("annotations_active", 0) + 1
                )

            mutable_predictions = list(
                self.session.scalars(
                    select(PredictionProposal).where(
                        PredictionProposal.project_id == source_class.project_id,
                        PredictionProposal.label_class_id == source_class.id,
                        PredictionProposal.review_status.in_(tuple(MUTABLE_PREDICTION_STATUSES)),
                    )
                )
            )
            for proposal in mutable_predictions:
                proposal.label_class_id = target_class.id
                proposal.was_edited = True
                affected_counts["prediction_proposals_pending"] = (
                    affected_counts.get("prediction_proposals_pending", 0) + 1
                )

            mutable_qc_issues = list(
                self.session.scalars(
                    select(QualityControlIssue).where(
                        QualityControlIssue.project_id == source_class.project_id,
                        QualityControlIssue.status.in_(tuple(MUTABLE_QC_STATUSES)),
                    )
                )
            )
            for issue in mutable_qc_issues:
                if source_class.id not in issue.class_ids_json:
                    continue
                issue.class_ids_json = _replace_class_id_list(
                    issue.class_ids_json, source_class.id, target_class.id
                )
                affected_counts["quality_control_issues_open"] = (
                    affected_counts.get("quality_control_issues_open", 0) + 1
                )

            mutable_review_queue_items = list(
                self.session.scalars(
                    select(ReviewQueueItem).where(
                        ReviewQueueItem.project_id == source_class.project_id,
                        ReviewQueueItem.review_state.in_(tuple(MUTABLE_REVIEW_STATES)),
                    )
                )
            )
            for item in mutable_review_queue_items:
                if source_class.id not in item.label_class_ids_json:
                    continue
                item.label_class_ids_json = _replace_class_id_list(
                    item.label_class_ids_json, source_class.id, target_class.id
                )
                affected_counts["review_queue_items_open"] = (
                    affected_counts.get("review_queue_items_open", 0) + 1
                )

            if operation_type == "reassign_delete":
                self.session.flush()
                # Check again after mutable reassignment, inside the write
                # transaction, even when the original preview was approved.
                remaining_usage = self.project_service._usage_snapshot(source_class)
                if any(
                    remaining_usage.counts[key] > 0 for key in UNHANDLED_CLASS_REFERENCE_CATEGORIES
                ):
                    raise ConflictError(
                        "Mask or image-level classification references still prevent "
                        "physical deletion of the source class."
                    )
                remaining_annotations = list(
                    self.session.scalars(
                        select(Annotation).where(Annotation.label_class_id == source_class.id)
                    )
                )
                remaining_historical_predictions = list(
                    self.session.scalars(
                        select(PredictionProposal).where(
                            PredictionProposal.project_id == source_class.project_id,
                            PredictionProposal.label_class_id == source_class.id,
                        )
                    )
                )
                if remaining_annotations or remaining_historical_predictions:
                    raise ConflictError(
                        "The source class still has protected references and cannot be "
                        "deleted safely."
                    )
                self.session.delete(source_class)
                final_state = "reassigned_and_deleted"
            else:
                final_state = "reassigned"

            operation.status = "completed"
            operation.completed_at = _utc_now()
            operation.final_state = final_state
            operation.failures_json = []
            operation.rollback_result_json = {"rolled_back": False}
            operation.plan_json = ClassOperationPlanResponse(
                mutable_records=current_plan.mutable_records,
                protected_records=current_plan.protected_records,
                blocking_records=current_plan.blocking_records,
                compatibility_impacts=current_plan.compatibility_impacts,
                warnings=current_plan.warnings,
                blockers=current_plan.blockers,
            ).model_dump(mode="json")
            operation.affected_counts_json = [
                self._group(key, USAGE_CATEGORY_META.get(key, (key, True, False))[0], [])
                .model_copy(update={"count": count})
                .model_dump(mode="json")
                for key, count in affected_counts.items()
            ]
            operation.protected_reference_counts_json = [
                group.model_dump(mode="json") for group in current_plan.protected_records
            ]
            operation.warnings_json = current_plan.warnings
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            operation = self._operation(payload.operation_id)
            operation.status = "rolled_back"
            operation.started_at = started_at
            operation.completed_at = _utc_now()
            operation.failures_json = [str(exc)]
            operation.rollback_result_json = {"rolled_back": True}
            operation.final_state = "rolled_back"
            self.session.commit()
            if isinstance(exc, ConflictError):
                raise
            raise

        return self._response(self._operation(payload.operation_id))

    def execute_reassign(
        self, project_id: str, class_id: str, payload: ClassOperationExecuteRequest
    ) -> ClassOperationResponse:
        return self._execute(
            operation_type="reassign",
            project_id=project_id,
            class_id=class_id,
            payload=payload,
        )

    def execute_reassign_delete(
        self, project_id: str, class_id: str, payload: ClassOperationExecuteRequest
    ) -> ClassOperationResponse:
        return self._execute(
            operation_type="reassign_delete",
            project_id=project_id,
            class_id=class_id,
            payload=payload,
        )
