"""Semantic raster-mask prediction review services."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    MaskAnnotation,
    MaskAnnotationEvent,
    PredictionProposal,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.annotations import AnnotationResponse, MaskAnnotationResponse
from reefvision.schemas.predictions import (
    PredictionAcceptRequest,
    PredictionBulkReviewRequest,
    PredictionBulkReviewResponse,
    PredictionProposalResponse,
    PredictionReviewResponse,
)
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.services.segmentation_predictions import SegmentationPredictionService
from reefvision.storage.masks import write_mask_png
from reefvision.storage.projects import resolve_managed_project_path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SemanticPredictionService(SegmentationPredictionService):
    """Review box, polygon, and immutable raster-mask proposals."""

    def __init__(self, session: Session, settings: Settings) -> None:
        super().__init__(session)
        self.settings = settings

    def _response(self, proposal: PredictionProposal) -> PredictionProposalResponse:
        response = super()._response(proposal)
        response.mask_path = proposal.mask_path
        response.mask_content_sha256 = proposal.mask_content_sha256
        return response

    def raster_mask_file(self, proposal_id: str) -> Path:
        proposal = self._proposal(proposal_id)
        if proposal.geometry_kind != "raster_mask" or not proposal.mask_path:
            raise NotFoundError("Semantic proposal mask not found")
        path = resolve_managed_project_path(self.settings, proposal.mask_path)
        if not path.is_file():
            raise NotFoundError("Semantic proposal mask file not found")
        if proposal.mask_content_sha256 and _file_sha256(path) != proposal.mask_content_sha256:
            raise ValidationError("Semantic proposal mask checksum does not match")
        return path

    def _create_raster_mask_from_proposal(
        self,
        proposal: PredictionProposal,
        payload: PredictionAcceptRequest | None,
    ) -> MaskAnnotation:
        image = self._image(proposal.image_id)
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if proposal.review_status != "pending":
            raise ConflictError("Only pending prediction proposals can be reviewed")
        label_class_id = self._resolve_accept_class(image, proposal, payload)
        if not proposal.mask_content_sha256:
            raise ValidationError("Semantic proposal mask metadata is missing")
        source_path = self.raster_mask_file(proposal.id)

        annotation_id = str(uuid4())
        relative_path, _destination, area, x_min, y_min, x_max, y_max = write_mask_png(
            self.settings,
            project_storage_root=project.storage_root,
            image_id=image.id,
            mask_annotation_id=annotation_id,
            png_base64=base64.b64encode(source_path.read_bytes()).decode("ascii"),
            expected_width=image.width_px,
            expected_height=image.height_px,
        )
        model = self.models.get(proposal.model_id)
        class_changed = label_class_id != proposal.label_class_id
        annotation = MaskAnnotation(
            id=annotation_id,
            image_id=image.id,
            label_class_id=label_class_id,
            geometry_kind="raster_mask",
            mask_path=relative_path,
            polygon_json=None,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            area_pixels=area,
            source_type="accepted_prediction",
            provenance_json={
                "provider_name": model.provider_name if model is not None else None,
                "provider_version": model.provider_version if model is not None else None,
                "model_checksum": proposal.model_checksum,
                "source_model_id": proposal.model_id,
                "source_prediction_id": proposal.id,
                "inference_job_id": proposal.inference_job_id,
                "original_confidence": proposal.confidence,
                "original_predicted_label": proposal.predicted_label,
                "proposal_mask_path": proposal.mask_path,
                "proposal_mask_sha256": proposal.mask_content_sha256,
                "accepted_mask_path": relative_path,
                "class_changed": class_changed,
                "accepted_at": _utc_now().isoformat(),
            },
            status="verified",
            created_by="local_user",
            revision=1,
        )
        proposal.review_status = "edited_and_accepted" if class_changed else "accepted"
        proposal.was_edited = class_changed
        proposal.reviewer_action_at = _utc_now()
        proposal.accepted_mask_annotation_id = annotation.id
        proposal.provenance_json = {
            **(proposal.provenance_json or {}),
            "accepted_label_class_id": label_class_id,
            "accepted_mask_annotation_id": annotation.id,
            "accepted_mask_path": relative_path,
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
        if proposal.geometry_kind != "raster_mask":
            return super().accept(proposal_id, payload)
        annotation = self._create_raster_mask_from_proposal(proposal, payload)
        self.session.commit()
        self.session.refresh(annotation)
        self.session.refresh(proposal)
        return PredictionReviewResponse(
            proposal=self._response(proposal),
            annotation=None,
            mask_annotation=MaskAnnotationResponse.model_validate(annotation),
        )

    def bulk_review(
        self,
        payload: PredictionBulkReviewRequest,
    ) -> PredictionBulkReviewResponse:
        proposals = self.predictions.list_by_ids(payload.proposal_ids)
        if not any(item.geometry_kind == "raster_mask" for item in proposals):
            return super().bulk_review(payload)
        if len(proposals) != len(payload.proposal_ids):
            raise ValidationError("One or more prediction proposals do not exist")
        boxes: list[Annotation] = []
        masks: list[MaskAnnotation] = []
        if payload.action == "reject":
            for proposal in proposals:
                if proposal.review_status != "pending":
                    raise ConflictError("Bulk review only supports pending proposals")
                proposal.review_status = "rejected"
                proposal.reviewer_action_at = _utc_now()
        else:
            for proposal in proposals:
                if proposal.geometry_kind == "raster_mask":
                    masks.append(self._create_raster_mask_from_proposal(proposal, None))
                elif proposal.geometry_kind == "polygon_mask":
                    masks.append(self._create_mask_from_proposal(proposal, None))
                else:
                    boxes.append(self._create_annotation_from_proposal(proposal, None))
        self.session.flush()
        created_boxes = [AnnotationResponse.model_validate(item) for item in boxes]
        created_masks = [MaskAnnotationResponse.model_validate(item) for item in masks]
        self.session.commit()
        return PredictionBulkReviewResponse(
            reviewed_count=len(proposals),
            created_annotations=created_boxes,
            created_mask_annotations=created_masks,
        )
