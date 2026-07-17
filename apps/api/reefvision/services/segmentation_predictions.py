"""Segmentation-aware prediction review services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    MaskAnnotation,
    MaskAnnotationEvent,
    PredictionProposal,
)
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.schemas.annotations import AnnotationResponse, MaskAnnotationResponse
from reefvision.schemas.predictions import (
    PredictionAcceptRequest,
    PredictionBulkReviewRequest,
    PredictionBulkReviewResponse,
    PredictionProposalResponse,
    PredictionReviewResponse,
)
from reefvision.services.annotations import (
    _polygon_area,
    _polygon_self_intersects,
    mask_annotation_snapshot,
)
from reefvision.services.predictions import PredictionService

Point = tuple[float, float]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SegmentationPredictionService(PredictionService):
    """Review box proposals and polygon-mask proposals through one API."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.mask_annotations = MaskAnnotationRepository(session)

    def _response(
        self,
        proposal: PredictionProposal,
    ) -> PredictionProposalResponse:
        response = super()._response(proposal)
        response.geometry_kind = proposal.geometry_kind
        response.polygon_json = proposal.polygon_json
        response.accepted_mask_annotation_id = (
            proposal.accepted_mask_annotation_id
        )
        return response

    def _validated_polygon(
        self,
        proposal: PredictionProposal,
        payload: PredictionAcceptRequest | None,
    ) -> tuple[list[list[float]], float, float, float, float, int]:
        image = self._image(proposal.image_id)
        raw = (
            payload.polygon_json
            if payload and payload.polygon_json
            else proposal.polygon_json
        )
        if not raw or len(raw) < 3:
            raise ValidationError(
                "Segmentation proposals require at least three polygon points"
            )
        points: list[Point] = [
            (float(point[0]), float(point[1])) for point in raw
        ]
        if len(set(points)) < 3:
            raise ValidationError(
                "Segmentation proposals require at least three unique points"
            )
        if any(
            x < 0
            or y < 0
            or x > image.width_px
            or y > image.height_px
            for x, y in points
        ):
            raise ValidationError(
                "Segmentation proposal polygons must remain inside the source image"
            )
        if _polygon_self_intersects(points):
            raise ValidationError(
                "Segmentation proposal polygons may not self-intersect"
            )
        area = _polygon_area(points)
        if area <= 0:
            raise ValidationError(
                "Segmentation proposal polygons must have positive area"
            )
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (
            [[x, y] for x, y in points],
            min(xs),
            min(ys),
            max(xs),
            max(ys),
            max(round(area), 1),
        )

    def _create_mask_from_proposal(
        self,
        proposal: PredictionProposal,
        payload: PredictionAcceptRequest | None,
    ) -> MaskAnnotation:
        image = self._image(proposal.image_id)
        if proposal.review_status != "pending":
            raise ConflictError(
                "Only pending prediction proposals can be reviewed"
            )
        label_class_id = (
            payload.label_class_id
            if payload and payload.label_class_id
            else proposal.label_class_id
        )
        if label_class_id is None:
            raise ValidationError(
                "Choose a project class before accepting this prediction"
            )
        self._label_class(image, label_class_id)
        polygon, x_min, y_min, x_max, y_max, area_pixels = (
            self._validated_polygon(proposal, payload)
        )
        original_polygon = proposal.polygon_json or []
        edited = (
            label_class_id != proposal.label_class_id
            or polygon != original_polygon
        )
        model = self.models.get(proposal.model_id)
        annotation = MaskAnnotation(
            id=str(uuid4()),
            image_id=image.id,
            label_class_id=label_class_id,
            geometry_kind="polygon",
            mask_path=None,
            polygon_json=polygon,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            area_pixels=area_pixels,
            source_type="accepted_prediction",
            provenance_json={
                "provider_name": (
                    model.provider_name if model is not None else None
                ),
                "provider_version": (
                    model.provider_version if model is not None else None
                ),
                "model_checksum": proposal.model_checksum,
                "source_model_id": proposal.model_id,
                "source_prediction_id": proposal.id,
                "inference_job_id": proposal.inference_job_id,
                "original_confidence": proposal.confidence,
                "original_predicted_label": proposal.predicted_label,
                "original_polygon": original_polygon,
                "accepted_polygon": polygon,
                "class_changed": label_class_id != proposal.label_class_id,
                "geometry_changed": polygon != original_polygon,
                "accepted_at": _utc_now().isoformat(),
            },
            status="verified",
            created_by="local_user",
            revision=1,
        )
        proposal.review_status = (
            "edited_and_accepted" if edited else "accepted"
        )
        proposal.was_edited = edited
        proposal.reviewer_action_at = _utc_now()
        proposal.accepted_mask_annotation_id = annotation.id
        proposal.provenance_json = {
            **(proposal.provenance_json or {}),
            "accepted_polygon": polygon,
            "accepted_label_class_id": label_class_id,
            "accepted_mask_annotation_id": annotation.id,
        }
        image.annotation_revision += 1
        if image.annotation_status == "unannotated":
            image.annotation_status = "in_progress"
        self.mask_annotations.add(annotation)
        self.mask_annotations.add_event(
            MaskAnnotationEvent(
                mask_annotation_id=annotation.id,
                image_id=image.id,
                event_type="created",
                before_json=None,
                after_json=mask_annotation_snapshot(annotation),
                actor="local_user",
            )
        )
        return annotation

    def accept(
        self,
        proposal_id: str,
        payload: PredictionAcceptRequest,
    ) -> PredictionReviewResponse:
        proposal = self._proposal(proposal_id)
        if proposal.geometry_kind != "polygon_mask":
            return super().accept(proposal_id, payload)
        mask_annotation = self._create_mask_from_proposal(
            proposal,
            payload,
        )
        self.session.commit()
        self.session.refresh(mask_annotation)
        self.session.refresh(proposal)
        return PredictionReviewResponse(
            proposal=self._response(proposal),
            annotation=None,
            mask_annotation=MaskAnnotationResponse.model_validate(
                mask_annotation
            ),
        )

    def reject(self, proposal_id: str) -> PredictionReviewResponse:
        response = super().reject(proposal_id)
        response.mask_annotation = None
        return response

    def bulk_review(
        self,
        payload: PredictionBulkReviewRequest,
    ) -> PredictionBulkReviewResponse:
        proposals = self.predictions.list_by_ids(payload.proposal_ids)
        if len(proposals) != len(payload.proposal_ids):
            raise ValidationError(
                "One or more prediction proposals do not exist"
            )
        box_annotations: list[Annotation] = []
        mask_annotations: list[MaskAnnotation] = []
        if payload.action == "reject":
            for proposal in proposals:
                if proposal.review_status != "pending":
                    raise ConflictError(
                        "Bulk review only supports pending proposals"
                    )
                proposal.review_status = "rejected"
                proposal.reviewer_action_at = _utc_now()
        else:
            for proposal in proposals:
                if proposal.geometry_kind == "polygon_mask":
                    mask_annotations.append(
                        self._create_mask_from_proposal(proposal, None)
                    )
                else:
                    box_annotations.append(
                        self._create_annotation_from_proposal(proposal, None)
                    )
        self.session.flush()
        created_annotations = [
            AnnotationResponse.model_validate(annotation)
            for annotation in box_annotations
        ]
        created_mask_annotations = [
            MaskAnnotationResponse.model_validate(annotation)
            for annotation in mask_annotations
        ]
        self.session.commit()
        return PredictionBulkReviewResponse(
            reviewed_count=len(proposals),
            created_annotations=created_annotations,
            created_mask_annotations=created_mask_annotations,
        )
