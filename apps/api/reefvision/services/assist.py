"""Interactive SAM-style annotation assist services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ImageAsset,
    ModelRegistration,
    PredictionProposal,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.assist_runtime import AssistRuntime, AssistSessionState
from reefvision.ml.providers import BrushStroke, PixelBox, PixelPoint
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.predictions import PredictionRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotations import AnnotationResponse
from reefvision.schemas.assist import (
    AssistAcceptRequest,
    AssistAcceptResponse,
    AssistBoxRequest,
    AssistBrushRequest,
    AssistCandidateBox,
    AssistSessionCreateRequest,
    AssistSessionResponse,
)
from reefvision.services.annotations import annotation_snapshot
from reefvision.storage.projects import resolve_managed_project_path


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AssistService:
    def __init__(self, session: Session, settings: Settings, runtime: AssistRuntime) -> None:
        self.session = session
        self.settings = settings
        self.runtime = runtime
        self.projects = ProjectRepository(session)
        self.images = ImageRepository(session)
        self.models = ModelRepository(session)
        self.annotations = AnnotationRepository(session)
        self.predictions = PredictionRepository(session)

    def _image(self, image_id: str) -> ImageAsset:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _model(self, model_id: str) -> ModelRegistration:
        model = self.models.get(model_id)
        if model is None:
            raise NotFoundError("Model not found")
        return model

    def _source_prediction(self, image: ImageAsset, proposal_id: str) -> PredictionProposal:
        proposal = self.predictions.get(proposal_id)
        if proposal is None:
            raise NotFoundError("Prediction proposal not found")
        if proposal.project_id != image.project_id or proposal.image_id != image.id:
            raise ValidationError(
                "Prompt Assist proposals must belong to the same project image "
                "as the assist session"
            )
        if proposal.review_status != "pending":
            raise ConflictError(
                "Only pending prediction proposals can be segmented with Prompt Assist"
            )
        return proposal

    def _response(self, session_state: AssistSessionState) -> AssistSessionResponse:
        candidate_box = None
        if session_state.candidate_prediction is not None:
            candidate_box = AssistCandidateBox(
                x_min=session_state.candidate_prediction.box.x_min,
                y_min=session_state.candidate_prediction.box.y_min,
                x_max=session_state.candidate_prediction.box.x_max,
                y_max=session_state.candidate_prediction.box.y_max,
            )
        return AssistSessionResponse(
            session_id=session_state.session_id,
            project_id=session_state.project_id,
            image_id=session_state.image_id,
            model_id=session_state.model_id,
            model_display_name=session_state.model_display_name,
            provider_name=session_state.provider_name,
            provider_version=session_state.provider_version,
            created_at=session_state.created_at,
            last_used_at=session_state.last_used_at,
            expires_at=session_state.expires_at,
            add_stroke_count=len(session_state.add_strokes),
            subtract_stroke_count=len(session_state.subtract_strokes),
            brush_radius=session_state.brush_radius,
            source_prediction_id=session_state.source_prediction_id,
            prompt_type=session_state.prompt_type,
            candidate_box=candidate_box,
            candidate_mask_png_base64=session_state.candidate_mask_png_base64,
        )

    def create_session(
        self, image_id: str, payload: AssistSessionCreateRequest
    ) -> AssistSessionResponse:
        image = self._image(image_id)
        model = self._model(payload.model_id)
        if model.project_id != image.project_id or model.purpose != "assist":
            raise ValidationError("Assist sessions require an assist model from the same project")
        source_prediction_id = None
        if payload.source_prediction_id:
            source_prediction_id = self._source_prediction(
                image, payload.source_prediction_id
            ).id
        image_path = resolve_managed_project_path(self.settings, image.managed_path)
        model_path = resolve_managed_project_path(self.settings, model.managed_path)
        session_state = self.runtime.create_session(
            project_id=image.project_id,
            image_id=image.id,
            image_sha256=image.sha256,
            image_path=image_path,
            model_id=model.id,
            model_display_name=model.display_name,
            model_checksum=model.sha256,
            model_path=model_path,
            provider_name=model.provider_name,
            provider_version=model.provider_version,
            device=payload.device,
            source_prediction_id=source_prediction_id,
        )
        return self._response(session_state)

    def brush(self, session_id: str, payload: AssistBrushRequest) -> AssistSessionResponse:
        image_id = self.runtime._session(session_id).image_id
        image = self._image(image_id)
        strokes = [
            BrushStroke(
                points=[PixelPoint(x=point.x, y=point.y) for point in stroke.points],
                brush_radius=float(payload.brush_radius),
            )
            for stroke in payload.strokes
        ]
        state = self.runtime.apply_brush_prompts(
            session_id=session_id,
            strokes=strokes,
            mode=payload.mode,
            image_width=image.width_px,
            image_height=image.height_px,
        )
        return self._response(state)

    def box(self, session_id: str, payload: AssistBoxRequest) -> AssistSessionResponse:
        if payload.x_max <= payload.x_min or payload.y_max <= payload.y_min:
            raise ValidationError("Bounding boxes must have positive width and height")
        state = self.runtime.apply_box_prompt(
            session_id=session_id,
            box=PixelBox(
                x_min=payload.x_min,
                y_min=payload.y_min,
                x_max=payload.x_max,
                y_max=payload.y_max,
            ),
        )
        return self._response(state)

    def reset(self, session_id: str) -> AssistSessionResponse:
        return self._response(self.runtime.reset_session(session_id))

    def accept(self, session_id: str, payload: AssistAcceptRequest) -> AssistAcceptResponse:
        session_state, box, provenance = self.runtime.accept_session(session_id)
        image = self._image(session_state.image_id)
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if payload.label_class_id not in {label_class.id for label_class in project.label_classes}:
            raise ValidationError("Annotation class does not belong to this image's project")
        annotation = Annotation(
            id=str(uuid4()),
            image_id=image.id,
            label_class_id=payload.label_class_id,
            x_min=box.x_min,
            y_min=box.y_min,
            x_max=box.x_max,
            y_max=box.y_max,
            source_type="assist_mask",
            source_model_id=session_state.model_id,
            source_prediction_id=session_state.source_prediction_id,
            provenance_json=provenance,
        )
        if session_state.source_prediction_id is not None:
            self._attach_source_prediction(
                image=image,
                proposal_id=session_state.source_prediction_id,
                annotation=annotation,
                label_class_id=payload.label_class_id,
            )
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
        image.annotation_revision += 1
        if image.annotation_status == "unannotated":
            image.annotation_status = "in_progress"
        self.session.commit()
        self.session.refresh(annotation)
        self.runtime.delete_session(session_id)
        return AssistAcceptResponse(
            session_id=session_id,
            annotation=AnnotationResponse.model_validate(annotation),
        )

    def cancel(self, session_id: str) -> None:
        self.runtime.delete_session(session_id)

    def _attach_source_prediction(
        self,
        *,
        image: ImageAsset,
        proposal_id: str,
        annotation: Annotation,
        label_class_id: str,
    ) -> None:
        proposal = self._source_prediction(image, proposal_id)
        edited = (
            label_class_id != proposal.label_class_id
            or annotation.x_min != proposal.x_min
            or annotation.y_min != proposal.y_min
            or annotation.x_max != proposal.x_max
            or annotation.y_max != proposal.y_max
        )
        proposal.review_status = "edited_and_accepted" if edited else "accepted"
        proposal.was_edited = edited
        proposal.reviewer_action_at = _utc_now()
        proposal.accepted_annotation_id = annotation.id
        proposal.provenance_json = {
            **(proposal.provenance_json or {}),
            "assist_acceptance": {
                "assist_model_id": annotation.source_model_id,
                "accepted_annotation_id": annotation.id,
                "accepted_label_class_id": label_class_id,
                "accepted_box": {
                    "x_min": annotation.x_min,
                    "y_min": annotation.y_min,
                    "x_max": annotation.x_max,
                    "y_max": annotation.y_max,
                },
                "accepted_at": _utc_now().isoformat(),
            },
        }
        annotation.provenance_json = {
            **(annotation.provenance_json or {}),
            "source_prediction": {
                "proposal_id": proposal.id,
                "inference_job_id": proposal.inference_job_id,
                "model_id": proposal.model_id,
                "model_checksum": proposal.model_checksum,
                "original_predicted_label": proposal.predicted_label,
                "original_confidence": proposal.confidence,
                "original_box": {
                    "x_min": proposal.x_min,
                    "y_min": proposal.y_min,
                    "x_max": proposal.x_max,
                    "y_max": proposal.y_max,
                },
                "review_status_after_accept": proposal.review_status,
            },
        }
