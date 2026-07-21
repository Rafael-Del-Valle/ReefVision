"""Semantic raster-mask prediction review services."""

from __future__ import annotations

import base64
from contextlib import suppress
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
from reefvision.storage.masks import (
    remove_mask_annotation_png,
    resolve_prediction_mask_png,
    write_mask_png,
)

MaskCleanupTarget = tuple[str, str, str, str]


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
        image = self._image(proposal.image_id)
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        path = resolve_prediction_mask_png(
            self.settings,
            project_storage_root=project.storage_root,
            proposal_id=proposal.id,
            relative_path=proposal.mask_path,
        )
        if not path.is_file():
            raise NotFoundError("Semantic proposal mask file not found")
        if proposal.mask_content_sha256 and _file_sha256(path) != proposal.mask_content_sha256:
            raise ValidationError("Semantic proposal mask checksum does not match")
        return path

    def _create_raster_mask_from_proposal(
        self,
        proposal: PredictionProposal,
        payload: PredictionAcceptRequest | None,
        cleanup_targets: list[MaskCleanupTarget],
    ) -> MaskAnnotation:
        image = self._image(proposal.image_id)
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
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
        if not proposal.mask_content_sha256:
            raise ValidationError("Semantic proposal mask metadata is missing")
        source_path = self.raster_mask_file(proposal.id)
        model = self.models.get(proposal.model_id)

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
        cleanup_targets.append((project.storage_root, image.id, annotation_id, relative_path))
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
                "source_run_id": proposal.inference_job_id,
                "original_confidence": proposal.confidence,
                "original_predicted_label": proposal.predicted_label,
                "original_predicted_index": proposal.predicted_index,
                "original_label_class_id": proposal.label_class_id,
                "original_predicted_box": {
                    "x_min": proposal.x_min,
                    "y_min": proposal.y_min,
                    "x_max": proposal.x_max,
                    "y_max": proposal.y_max,
                },
                "proposal_mask_path": proposal.mask_path,
                "proposal_mask_sha256": proposal.mask_content_sha256,
                "accepted_mask_path": relative_path,
                "source_proposal_provenance": proposal.provenance_json,
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

    def _remove_mask_copies(self, cleanup_targets: list[MaskCleanupTarget]) -> None:
        for project_storage_root, image_id, annotation_id, relative_path in cleanup_targets:
            with suppress(Exception):
                remove_mask_annotation_png(
                    self.settings,
                    project_storage_root=project_storage_root,
                    image_id=image_id,
                    mask_annotation_id=annotation_id,
                    relative_path=relative_path,
                )

    def accept(
        self,
        proposal_id: str,
        payload: PredictionAcceptRequest,
    ) -> PredictionReviewResponse:
        proposal = self._proposal(proposal_id)
        if proposal.geometry_kind != "raster_mask":
            return super().accept(proposal_id, payload)
        existing = self._accepted_mask_for_retry(proposal)
        if existing is not None:
            return PredictionReviewResponse(
                proposal=self._response(proposal),
                annotation=None,
                mask_annotation=MaskAnnotationResponse.model_validate(existing),
            )
        cleanup_targets: list[MaskCleanupTarget] = []
        try:
            annotation = self._create_raster_mask_from_proposal(
                proposal,
                payload,
                cleanup_targets,
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            self._remove_mask_copies(cleanup_targets)
            raise
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
        cleanup_targets: list[MaskCleanupTarget] = []
        try:
            if payload.action == "reject":
                for proposal in proposals:
                    if proposal.review_status != "pending":
                        raise ConflictError("Bulk review only supports pending proposals")
                    proposal.review_status = "rejected"
                    proposal.reviewer_action_at = _utc_now()
            else:
                for proposal in proposals:
                    if proposal.geometry_kind == "raster_mask":
                        annotation = self._create_raster_mask_from_proposal(
                            proposal,
                            None,
                            cleanup_targets,
                        )
                        masks.append(annotation)
                    elif proposal.geometry_kind == "polygon_mask":
                        masks.append(self._create_mask_from_proposal(proposal, None))
                    else:
                        boxes.append(self._create_annotation_from_proposal(proposal, None))
            self.session.flush()
            created_boxes = [AnnotationResponse.model_validate(item) for item in boxes]
            created_masks = [MaskAnnotationResponse.model_validate(item) for item in masks]
            self.session.commit()
        except Exception:
            self.session.rollback()
            self._remove_mask_copies(cleanup_targets)
            raise
        return PredictionBulkReviewResponse(
            reviewed_count=len(proposals),
            created_annotations=created_boxes,
            created_mask_annotations=created_masks,
        )
