"""Prediction-proposal listing and review services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ImageAsset,
    LabelClass,
    PredictionProposal,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.predictions import PredictionRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotations import AnnotationResponse
from reefvision.schemas.predictions import (
    PredictionAcceptRequest,
    PredictionBulkReviewRequest,
    PredictionBulkReviewResponse,
    PredictionListResponse,
    PredictionProposalResponse,
    PredictionReviewResponse,
)
from reefvision.services.annotations import annotation_snapshot


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PredictionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.images = ImageRepository(session)
        self.models = ModelRepository(session)
        self.predictions = PredictionRepository(session)
        self.annotations = AnnotationRepository(session)

    def _image(self, image_id: str) -> ImageAsset:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _proposal(self, proposal_id: str) -> PredictionProposal:
        proposal = self.predictions.get(proposal_id)
        if proposal is None:
            raise NotFoundError("Prediction proposal not found")
        return proposal

    def _label_class(self, image: ImageAsset, label_class_id: str) -> LabelClass:
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        for label_class in project.label_classes:
            if label_class.id == label_class_id:
                return label_class
        raise ValidationError("Annotation class does not belong to this image's project")

    def _response(self, proposal: PredictionProposal) -> PredictionProposalResponse:
        model = self.models.get(proposal.model_id)
        return PredictionProposalResponse(
            id=proposal.id,
            project_id=proposal.project_id,
            image_id=proposal.image_id,
            model_id=proposal.model_id,
            model_display_name=model.display_name if model is not None else proposal.model_id,
            inference_job_id=proposal.inference_job_id,
            model_checksum=proposal.model_checksum,
            label_class_id=proposal.label_class_id,
            predicted_label=proposal.predicted_label,
            predicted_index=proposal.predicted_index,
            confidence=proposal.confidence,
            x_min=proposal.x_min,
            y_min=proposal.y_min,
            x_max=proposal.x_max,
            y_max=proposal.y_max,
            review_status=proposal.review_status,
            was_edited=proposal.was_edited,
            reviewer_action_at=proposal.reviewer_action_at,
            accepted_annotation_id=proposal.accepted_annotation_id,
            inference_settings_json=proposal.inference_settings_json,
            provenance_json=proposal.provenance_json,
            created_at=proposal.created_at,
        )

    def list_for_image(
        self,
        image_id: str,
        *,
        model_id: str | None,
        label_class_id: str | None,
        min_confidence: float | None,
        review_status: str | None,
    ) -> PredictionListResponse:
        self._image(image_id)
        items = self.predictions.list_for_image(
            image_id,
            model_id=model_id,
            label_class_id=label_class_id,
            min_confidence=min_confidence,
            review_status=review_status,
        )
        return PredictionListResponse(
            items=[self._response(item) for item in items],
            counts=self.predictions.counts_for_image(image_id),
        )

    def _validated_box(
        self,
        image: ImageAsset,
        *,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
    ) -> tuple[float, float, float, float]:
        if x_max <= x_min or y_max <= y_min:
            raise ValidationError("Bounding boxes must have positive width and height")
        if x_min < 0 or y_min < 0 or x_max > image.width_px or y_max > image.height_px:
            raise ValidationError("Bounding boxes must remain inside the source image")
        return x_min, y_min, x_max, y_max

    def _create_annotation_from_proposal(
        self,
        proposal: PredictionProposal,
        payload: PredictionAcceptRequest | None,
    ) -> Annotation:
        image = self._image(proposal.image_id)
        if proposal.review_status != "pending":
            raise ConflictError("Only pending prediction proposals can be reviewed")
        label_class_id = (
            payload.label_class_id
            if payload and payload.label_class_id
            else proposal.label_class_id
        )
        if label_class_id is None:
            raise ValidationError("Choose a project class before accepting this prediction")
        self._label_class(image, label_class_id)
        x_min = payload.x_min if payload and payload.x_min is not None else proposal.x_min
        y_min = payload.y_min if payload and payload.y_min is not None else proposal.y_min
        x_max = payload.x_max if payload and payload.x_max is not None else proposal.x_max
        y_max = payload.y_max if payload and payload.y_max is not None else proposal.y_max
        x_min, y_min, x_max, y_max = self._validated_box(
            image, x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max
        )
        edited = (
            label_class_id != proposal.label_class_id
            or x_min != proposal.x_min
            or y_min != proposal.y_min
            or x_max != proposal.x_max
            or y_max != proposal.y_max
        )
        model = self.models.get(proposal.model_id)
        annotation = Annotation(
            id=str(uuid4()),
            image_id=image.id,
            label_class_id=label_class_id,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            source_type="accepted_prediction",
            source_model_id=proposal.model_id,
            source_prediction_id=proposal.id,
            provenance_json={
                "provider_name": model.provider_name if model is not None else None,
                "provider_version": model.provider_version if model is not None else None,
                "model_checksum": proposal.model_checksum,
                "inference_job_id": proposal.inference_job_id,
                "original_confidence": proposal.confidence,
                "original_predicted_label": proposal.predicted_label,
                "original_predicted_box": {
                    "x_min": proposal.x_min,
                    "y_min": proposal.y_min,
                    "x_max": proposal.x_max,
                    "y_max": proposal.y_max,
                },
                "accepted_box": {
                    "x_min": x_min,
                    "y_min": y_min,
                    "x_max": x_max,
                    "y_max": y_max,
                },
                "class_changed": label_class_id != proposal.label_class_id,
                "geometry_changed": edited
                and (
                    x_min != proposal.x_min
                    or y_min != proposal.y_min
                    or x_max != proposal.x_max
                    or y_max != proposal.y_max
                ),
                "accepted_at": _utc_now().isoformat(),
            },
        )
        proposal.review_status = "edited_and_accepted" if edited else "accepted"
        proposal.was_edited = edited
        proposal.reviewer_action_at = _utc_now()
        proposal.accepted_annotation_id = annotation.id
        proposal.provenance_json = {
            **(proposal.provenance_json or {}),
            "accepted_box": {
                "x_min": x_min,
                "y_min": y_min,
                "x_max": x_max,
                "y_max": y_max,
            },
            "accepted_label_class_id": label_class_id,
        }
        image.annotation_revision += 1
        if image.annotation_status == "unannotated":
            image.annotation_status = "in_progress"
        self.annotations.add(annotation)
        self.annotations.add_event(
            AnnotationEvent(
                annotation_id=annotation.id,
                image_id=image.id,
                event_type="created",
                before_json=None,
                after_json=annotation_snapshot(annotation),
                actor="local_user",
            )
        )
        return annotation

    def accept(
        self, proposal_id: str, payload: PredictionAcceptRequest
    ) -> PredictionReviewResponse:
        proposal = self._proposal(proposal_id)
        annotation = self._create_annotation_from_proposal(proposal, payload)
        self.session.commit()
        self.session.refresh(annotation)
        self.session.refresh(proposal)
        return PredictionReviewResponse(
            proposal=self._response(proposal),
            annotation=AnnotationResponse.model_validate(annotation),
        )

    def reject(self, proposal_id: str) -> PredictionReviewResponse:
        proposal = self._proposal(proposal_id)
        if proposal.review_status != "pending":
            raise ConflictError("Only pending prediction proposals can be reviewed")
        proposal.review_status = "rejected"
        proposal.reviewer_action_at = _utc_now()
        self.session.commit()
        self.session.refresh(proposal)
        return PredictionReviewResponse(proposal=self._response(proposal), annotation=None)

    def bulk_review(self, payload: PredictionBulkReviewRequest) -> PredictionBulkReviewResponse:
        proposals = self.predictions.list_by_ids(payload.proposal_ids)
        if len(proposals) != len(payload.proposal_ids):
            raise ValidationError("One or more prediction proposals do not exist")
        created_annotations: list[AnnotationResponse] = []
        if payload.action == "reject":
            for proposal in proposals:
                if proposal.review_status != "pending":
                    raise ConflictError("Bulk review only supports pending proposals")
                proposal.review_status = "rejected"
                proposal.reviewer_action_at = _utc_now()
        else:
            for proposal in proposals:
                annotation = self._create_annotation_from_proposal(proposal, None)
                created_annotations.append(AnnotationResponse.model_validate(annotation))
        self.session.commit()
        return PredictionBulkReviewResponse(
            reviewed_count=len(proposals),
            created_annotations=created_annotations,
        )
