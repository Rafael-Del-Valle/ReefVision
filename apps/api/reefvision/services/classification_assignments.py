"""Structured classification label sets and independent reviewed assignments."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ClassificationAssignment,
    ClassificationLabelSet,
    ClassificationPrediction,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    ModelRegistration,
    Project,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.classification import (
    ClassificationAssignmentAcceptRequest,
    ClassificationAssignmentExportResponse,
    ClassificationAssignmentExportRow,
    ClassificationAssignmentPage,
    ClassificationAssignmentResponse,
    ClassificationLabelSetCreateRequest,
    ClassificationLabelSetResponse,
    ClassificationLabelSetUpdateRequest,
)


class ClassificationAssignmentService:
    """Manage classifier tasks whose outputs coexist on the same target."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _label_set(self, label_set_id: str) -> ClassificationLabelSet:
        label_set = self.session.get(ClassificationLabelSet, label_set_id)
        if label_set is None:
            raise NotFoundError("Classification label set not found")
        return label_set

    def _validate_allowed_classes(self, project_id: str, class_ids: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(class_ids))
        if not normalized:
            return []
        classes = list(
            self.session.scalars(
                select(LabelClass).where(
                    LabelClass.id.in_(normalized),
                    LabelClass.project_id == project_id,
                )
            )
        )
        if len(classes) != len(normalized):
            raise ValidationError(
                "Every allowed classification class must belong to the selected project"
            )
        return normalized

    def create_label_set(
        self,
        project_id: str,
        request: ClassificationLabelSetCreateRequest,
    ) -> ClassificationLabelSetResponse:
        self._project(project_id)
        key = request.key.strip().casefold()
        existing = self.session.scalar(
            select(ClassificationLabelSet).where(
                ClassificationLabelSet.project_id == project_id,
                func.lower(ClassificationLabelSet.key) == key,
            )
        )
        if existing is not None:
            raise ConflictError("A classification label set with this key already exists")
        allowed = self._validate_allowed_classes(project_id, request.allowed_class_ids)
        label_set = ClassificationLabelSet(
            project_id=project_id,
            key=key,
            name=request.name.strip(),
            description=request.description.strip() if request.description else None,
            target_kind=request.target_kind,
            cardinality=request.cardinality,
            allowed_class_ids_json=allowed,
            replaces_primary_class=request.replaces_primary_class,
            is_active=True,
            metadata_json=dict(request.metadata),
        )
        self.session.add(label_set)
        self.session.commit()
        self.session.refresh(label_set)
        return ClassificationLabelSetResponse.model_validate(label_set)

    def list_label_sets(
        self,
        project_id: str,
        *,
        target_kind: str | None = None,
        active_only: bool = True,
    ) -> list[ClassificationLabelSetResponse]:
        self._project(project_id)
        query = select(ClassificationLabelSet).where(
            ClassificationLabelSet.project_id == project_id
        )
        if target_kind:
            query = query.where(ClassificationLabelSet.target_kind == target_kind)
        if active_only:
            query = query.where(ClassificationLabelSet.is_active.is_(True))
        rows = list(
            self.session.scalars(
                query.order_by(ClassificationLabelSet.name, ClassificationLabelSet.key)
            )
        )
        return [ClassificationLabelSetResponse.model_validate(item) for item in rows]

    def update_label_set(
        self,
        label_set_id: str,
        request: ClassificationLabelSetUpdateRequest,
    ) -> ClassificationLabelSetResponse:
        label_set = self._label_set(label_set_id)
        if request.name is not None:
            label_set.name = request.name.strip()
        if "description" in request.model_fields_set:
            label_set.description = request.description.strip() if request.description else None
        if request.cardinality is not None:
            label_set.cardinality = request.cardinality
        if request.allowed_class_ids is not None:
            label_set.allowed_class_ids_json = self._validate_allowed_classes(
                label_set.project_id,
                request.allowed_class_ids,
            )
        if request.replaces_primary_class is not None:
            label_set.replaces_primary_class = request.replaces_primary_class
        if request.is_active is not None:
            label_set.is_active = request.is_active
        if request.metadata is not None:
            label_set.metadata_json = dict(request.metadata)
        self.session.commit()
        self.session.refresh(label_set)
        return ClassificationLabelSetResponse.model_validate(label_set)

    def _automatic_label_set(
        self,
        prediction: ClassificationPrediction,
        *,
        target_kind: str,
    ) -> ClassificationLabelSet:
        key = prediction.label_set.strip().casefold()
        label_set = self.session.scalar(
            select(ClassificationLabelSet).where(
                ClassificationLabelSet.project_id == prediction.project_id,
                func.lower(ClassificationLabelSet.key) == key,
            )
        )
        if label_set is not None:
            return label_set
        display_name = key.replace("_", " ").replace("-", " ").strip().title()
        model = self.session.get(ModelRegistration, prediction.model_id)
        label_set = ClassificationLabelSet(
            project_id=prediction.project_id,
            key=key,
            name=display_name or "Classification",
            description="Automatically created from a reviewed classifier prediction.",
            target_kind=target_kind,
            cardinality="single",
            allowed_class_ids_json=[],
            replaces_primary_class=key == "default",
            is_active=True,
            metadata_json={
                "created_from_prediction_id": prediction.id,
                "created_from_model_id": prediction.model_id,
                "created_from_model_name": model.display_name if model else None,
            },
        )
        self.session.add(label_set)
        self.session.flush()
        return label_set

    def _resolve_target(
        self,
        prediction: ClassificationPrediction,
    ) -> tuple[str, str, Annotation | None, ImageAsset]:
        image = self.session.get(ImageAsset, prediction.image_id)
        if image is None or image.project_id != prediction.project_id:
            raise ValidationError("The classification prediction has no valid source image")
        if prediction.annotation_id is None:
            return "image", f"image:{image.id}", None, image
        annotation = self.session.get(Annotation, prediction.annotation_id)
        if annotation is None or annotation.deleted_at is not None:
            raise ValidationError("The classification prediction has no active source annotation")
        if annotation.image_id != image.id:
            raise ValidationError(
                "The classification prediction no longer matches its source annotation"
            )
        source_revision = dict(prediction.provenance_json or {}).get(
            "source_annotation_revision"
        )
        if source_revision is not None:
            try:
                expected_revision = int(source_revision)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    "The classification prediction contains an invalid source revision"
                ) from exc
            if annotation.revision != expected_revision:
                raise ConflictError(
                    "The source annotation changed after classification inference; "
                    "run inference again before accepting this assignment"
                )
        return "annotation", f"annotation:{annotation.id}", annotation, image

    def _apply_primary_class(
        self,
        *,
        annotation: Annotation,
        image: ImageAsset,
        prediction: ClassificationPrediction,
        target_class: LabelClass,
    ) -> None:
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

    def accept_prediction_assignment(
        self,
        prediction_id: str,
        request: ClassificationAssignmentAcceptRequest,
    ) -> ClassificationAssignmentResponse:
        prediction = self.session.get(ClassificationPrediction, prediction_id)
        if prediction is None:
            raise NotFoundError("Classification prediction not found")
        if prediction.review_status == "rejected":
            raise ConflictError("A rejected classification prediction cannot be accepted")
        existing = self.session.scalar(
            select(ClassificationAssignment).where(
                ClassificationAssignment.source_prediction_id == prediction.id,
                ClassificationAssignment.status == "accepted",
            )
        )
        if existing is not None:
            return ClassificationAssignmentResponse.model_validate(existing)

        target_kind, target_key, annotation, image = self._resolve_target(prediction)
        if request.label_set_id:
            label_set = self._label_set(request.label_set_id)
            if label_set.project_id != prediction.project_id:
                raise ValidationError(
                    "The selected classification label set belongs to another project"
                )
        else:
            label_set = self._automatic_label_set(prediction, target_kind=target_kind)
        if not label_set.is_active:
            raise ValidationError("The selected classification label set is inactive")
        if label_set.target_kind != target_kind:
            raise ValidationError(
                f"This prediction targets {target_kind}, but the selected label set targets "
                f"{label_set.target_kind}"
            )

        target_class_id = request.label_class_id or prediction.label_class_id
        target_class = (
            self.session.get(LabelClass, target_class_id) if target_class_id is not None else None
        )
        if target_class is None or target_class.project_id != prediction.project_id:
            raise ValidationError("Choose a valid project class before accepting this assignment")
        allowed = list(label_set.allowed_class_ids_json or [])
        if allowed and target_class.id not in allowed:
            raise ValidationError(
                "The selected class is not allowed by this classification label set"
            )

        if label_set.cardinality == "single":
            current = list(
                self.session.scalars(
                    select(ClassificationAssignment).where(
                        ClassificationAssignment.label_set_id == label_set.id,
                        ClassificationAssignment.target_key == target_key,
                        ClassificationAssignment.status == "accepted",
                    )
                )
            )
            for assignment in current:
                assignment.status = "superseded"
                assignment.revision += 1
        else:
            duplicate = self.session.scalar(
                select(ClassificationAssignment).where(
                    ClassificationAssignment.label_set_id == label_set.id,
                    ClassificationAssignment.target_key == target_key,
                    ClassificationAssignment.label_class_id == target_class.id,
                    ClassificationAssignment.status == "accepted",
                )
            )
            if duplicate is not None:
                prediction.review_status = "accepted"
                prediction.accepted_label_class_id = target_class.id
                prediction.reviewed_at = datetime.now(UTC)
                self.session.commit()
                return ClassificationAssignmentResponse.model_validate(duplicate)

        source_revision = annotation.revision if annotation is not None else None
        if label_set.replaces_primary_class:
            if annotation is None:
                raise ValidationError(
                    "Only annotation label sets can replace a primary detection class"
                )
            self._apply_primary_class(
                annotation=annotation,
                image=image,
                prediction=prediction,
                target_class=target_class,
            )

        now = datetime.now(UTC)
        assignment = ClassificationAssignment(
            project_id=prediction.project_id,
            label_set_id=label_set.id,
            target_kind=target_kind,
            target_key=target_key,
            image_id=image.id,
            annotation_id=annotation.id if annotation else None,
            mask_annotation_id=None,
            fragment_key=None,
            label_class_id=target_class.id,
            source_type="accepted_prediction",
            source_model_id=prediction.model_id,
            source_prediction_id=prediction.id,
            confidence=prediction.confidence,
            probabilities_json=dict(prediction.probabilities_json or {}),
            status="accepted",
            provenance_json={
                "classification_mode": prediction.classification_mode,
                "predicted_label": prediction.predicted_label,
                "predicted_index": prediction.predicted_index,
                "source_annotation_revision": source_revision,
                "prediction_provenance": dict(prediction.provenance_json or {}),
            },
            reviewed_at=now,
        )
        self.session.add(assignment)
        prediction.review_status = "accepted"
        prediction.accepted_label_class_id = target_class.id
        prediction.reviewed_at = now
        self.session.commit()
        self.session.refresh(assignment)
        return ClassificationAssignmentResponse.model_validate(assignment)

    def list_assignments(
        self,
        project_id: str,
        *,
        page: int,
        page_size: int,
        image_id: str | None = None,
        annotation_id: str | None = None,
        label_set_id: str | None = None,
        model_id: str | None = None,
        status: str | None = "accepted",
    ) -> ClassificationAssignmentPage:
        self._project(project_id)
        filters = [ClassificationAssignment.project_id == project_id]
        if image_id:
            filters.append(ClassificationAssignment.image_id == image_id)
        if annotation_id:
            filters.append(ClassificationAssignment.annotation_id == annotation_id)
        if label_set_id:
            filters.append(ClassificationAssignment.label_set_id == label_set_id)
        if model_id:
            filters.append(ClassificationAssignment.source_model_id == model_id)
        if status:
            filters.append(ClassificationAssignment.status == status)
        total = int(
            self.session.scalar(select(func.count(ClassificationAssignment.id)).where(*filters))
            or 0
        )
        rows = list(
            self.session.scalars(
                select(ClassificationAssignment)
                .where(*filters)
                .order_by(
                    ClassificationAssignment.created_at.desc(),
                    ClassificationAssignment.id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return ClassificationAssignmentPage(
            items=[ClassificationAssignmentResponse.model_validate(item) for item in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    def export_assignments(
        self,
        project_id: str,
        *,
        status: str | None = "accepted",
    ) -> ClassificationAssignmentExportResponse:
        self._project(project_id)
        query = select(ClassificationAssignment).where(
            ClassificationAssignment.project_id == project_id
        )
        if status:
            query = query.where(ClassificationAssignment.status == status)
        assignments = list(
            self.session.scalars(
                query.order_by(
                    ClassificationAssignment.image_id,
                    ClassificationAssignment.target_key,
                    ClassificationAssignment.created_at,
                )
            )
        )
        rows: list[ClassificationAssignmentExportRow] = []
        for assignment in assignments:
            image = self.session.get(ImageAsset, assignment.image_id)
            label_set = self.session.get(ClassificationLabelSet, assignment.label_set_id)
            label_class = self.session.get(LabelClass, assignment.label_class_id)
            model = (
                self.session.get(ModelRegistration, assignment.source_model_id)
                if assignment.source_model_id
                else None
            )
            if image is None or label_set is None or label_class is None:
                continue
            annotation = (
                self.session.get(Annotation, assignment.annotation_id)
                if assignment.annotation_id
                else None
            )
            mask = (
                self.session.get(MaskAnnotation, assignment.mask_annotation_id)
                if assignment.mask_annotation_id
                else None
            )
            bounding_box: list[float] | None = None
            if annotation is not None:
                bounding_box = [
                    annotation.x_min,
                    annotation.y_min,
                    annotation.x_max,
                    annotation.y_max,
                ]
            elif mask is not None and None not in {
                mask.x_min,
                mask.y_min,
                mask.x_max,
                mask.y_max,
            }:
                bounding_box = [
                    float(mask.x_min),
                    float(mask.y_min),
                    float(mask.x_max),
                    float(mask.y_max),
                ]
            rows.append(
                ClassificationAssignmentExportRow(
                    assignment_id=assignment.id,
                    image_id=image.id,
                    image_filename=image.original_filename,
                    target_kind=assignment.target_kind,
                    target_key=assignment.target_key,
                    annotation_id=assignment.annotation_id,
                    mask_annotation_id=assignment.mask_annotation_id,
                    fragment_key=assignment.fragment_key,
                    bounding_box=bounding_box,
                    mask_geometry_kind=mask.geometry_kind if mask else None,
                    measurements=dict(mask.measurement_json or {}) if mask else {},
                    label_set_id=label_set.id,
                    label_set_key=label_set.key,
                    label_set_name=label_set.name,
                    cardinality=label_set.cardinality,
                    label_class_id=label_class.id,
                    label_class_name=label_class.name,
                    source_model_id=model.id if model else assignment.source_model_id,
                    source_model_name=model.display_name if model else None,
                    source_prediction_id=assignment.source_prediction_id,
                    confidence=assignment.confidence,
                    probabilities=dict(assignment.probabilities_json or {}),
                    status=assignment.status,
                    assignment_revision=assignment.revision,
                    provenance=dict(assignment.provenance_json or {}),
                    created_at=assignment.created_at,
                    reviewed_at=assignment.reviewed_at,
                )
            )
        return ClassificationAssignmentExportResponse(
            project_id=project_id,
            row_count=len(rows),
            rows=rows,
        )
