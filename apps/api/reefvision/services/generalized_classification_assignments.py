"""Accept reviewed classification predictions for all supported target kinds."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from reefvision.db.models import (
    Annotation,
    ClassificationAssignment,
    ClassificationPrediction,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.classification import (
    ClassificationAssignmentAcceptRequest,
    ClassificationAssignmentResponse,
)
from reefvision.services.classification_assignments import ClassificationAssignmentService


class GeneralizedClassificationAssignmentService(ClassificationAssignmentService):
    """Store reviewed classifier outputs without replacing unrelated target metadata."""

    def _resolved_target(
        self,
        prediction: ClassificationPrediction,
    ) -> tuple[
        str,
        str,
        Annotation | None,
        MaskAnnotation | None,
        ImageAsset,
        str | None,
        int | None,
    ]:
        image = self.session.get(ImageAsset, prediction.image_id)
        if image is None or image.project_id != prediction.project_id:
            raise ValidationError("The classification prediction has no valid source image")
        provenance = dict(prediction.provenance_json or {})
        target_kind = prediction.target_kind or (
            "annotation" if prediction.annotation_id else "image"
        )

        if target_kind == "annotation":
            annotation = (
                self.session.get(Annotation, prediction.annotation_id)
                if prediction.annotation_id
                else None
            )
            if annotation is None or annotation.deleted_at is not None:
                raise ValidationError(
                    "The classification prediction has no active source annotation"
                )
            if annotation.image_id != image.id:
                raise ValidationError(
                    "The classification prediction no longer matches its source annotation"
                )
            raw_revision = provenance.get("source_annotation_revision")
            if raw_revision is not None:
                try:
                    expected_revision = int(raw_revision)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(
                        "The classification prediction contains an invalid source revision"
                    ) from exc
                if annotation.revision != expected_revision:
                    raise ConflictError(
                        "The source annotation changed after classification inference; "
                        "run inference again before accepting this assignment"
                    )
            return (
                "annotation",
                prediction.target_key or f"annotation:{annotation.id}",
                annotation,
                None,
                image,
                None,
                annotation.revision,
            )

        if target_kind == "image":
            expected_checksum = provenance.get("source_image_checksum")
            if expected_checksum and str(expected_checksum) != image.sha256:
                raise ConflictError(
                    "The source image changed after classification inference; run inference again"
                )
            return (
                "image",
                prediction.target_key or f"image:{image.id}",
                None,
                None,
                image,
                None,
                image.annotation_revision,
            )

        if target_kind in {"mask", "fragment"}:
            mask = (
                self.session.get(MaskAnnotation, prediction.mask_annotation_id)
                if prediction.mask_annotation_id
                else None
            )
            if mask is None or mask.deleted_at is not None:
                raise ValidationError("The classification prediction has no active source mask")
            if mask.image_id != image.id:
                raise ValidationError(
                    "The classification prediction no longer matches its source mask"
                )
            raw_revision = provenance.get("source_mask_revision")
            if raw_revision is not None:
                try:
                    expected_revision = int(raw_revision)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(
                        "The classification prediction contains an invalid mask revision"
                    ) from exc
                if mask.revision != expected_revision:
                    raise ConflictError(
                        "The source mask changed after classification inference; "
                        "run inference again before accepting this assignment"
                    )
            fragment_key = prediction.fragment_key if target_kind == "fragment" else None
            target_key = prediction.target_key or (
                f"fragment:{fragment_key or mask.id}"
                if target_kind == "fragment"
                else f"mask:{mask.id}"
            )
            return (
                target_kind,
                target_key,
                None,
                mask,
                image,
                fragment_key,
                mask.revision,
            )
        raise ValidationError("The classification prediction has an unsupported target kind")

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

        (
            target_kind,
            target_key,
            annotation,
            mask,
            image,
            fragment_key,
            source_revision,
        ) = self._resolved_target(prediction)
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
            mask_annotation_id=mask.id if mask else None,
            fragment_key=fragment_key,
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
                "source_target_revision": source_revision,
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
